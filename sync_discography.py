#!/usr/bin/env python3
"""
Sincroniza discografia de todos os artistas que já foram sincronizados pelo menos uma vez.
Roda no workflow semanal após o scraper.

Uso: python sync_discography.py
Requer: SUPABASE_URL, SUPABASE_SERVICE_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
"""

import os
import sys
import time
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")


def sb_get(path):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def sb_delete(path):
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=15,
    )
    r.raise_for_status()


def sb_post(path, data):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json=data,
        timeout=30,
    )
    r.raise_for_status()


def sb_patch(path, data):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json=data,
        timeout=15,
    )
    r.raise_for_status()


_token_cache = {"token": None, "expires_at": 0}


def get_spotify_token():
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    return data["access_token"]


_request_count = 0
_rate_limit_hits = 0
_hard_limited = False  # Sinal de ban temporário (Retry-After > 300s)

RATE_LIMIT_THRESHOLD = 300  # Segundos — acima disso consideramos ban temporário


def spotify_get(url, token, max_retries=5):
    global _request_count, _rate_limit_hits, _hard_limited
    if _hard_limited:
        return None
    for attempt in range(max_retries):
        _request_count += 1
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r.status_code == 429:
            _rate_limit_hits += 1
            wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
            if wait > RATE_LIMIT_THRESHOLD:
                print(f"    ❌ Rate limit longo ({wait}s = {wait//3600}h{(wait%3600)//60}min) — abortando bloco")
                _hard_limited = True
                return None
            print(f"    ⏳ Rate limit #{_rate_limit_hits} (req #{_request_count}), aguardando {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    return None


def search_artist_id(name, token):
    """Search Spotify for an artist by name and return their ID."""
    url = f"https://api.spotify.com/v1/search?q={requests.utils.quote(name)}&type=artist&limit=5&market=BR"
    data = spotify_get(url, token)
    if not data:
        return None
    items = data.get("artists", {}).get("items", [])
    # Prefer exact match
    for item in items:
        if item["name"].lower() == name.lower():
            return item["id"]
    return items[0]["id"] if items else None


def fetch_artist_discography(artist_name, spotify_artist_id, token):
    """Fetch complete discography for an artist. Returns list of track dicts."""
    # 1. Get all albums
    albums = []
    url = f"https://api.spotify.com/v1/artists/{spotify_artist_id}/albums?include_groups=album,single,appears_on&limit=50&market=BR"
    while url:
        data = spotify_get(url, token)
        if not data:
            break
        albums.extend(data.get("items", []))
        url = data.get("next")
        time.sleep(0.1)

    # 2. Get tracks via batch album endpoint (up to 20 albums per request)
    album_track_map = {}  # track_id -> {album_name, release_date}
    all_track_ids = []
    for i in range(0, len(albums), 20):
        batch_albums = albums[i:i + 20]
        batch_ids = [a["id"] for a in batch_albums]
        data = spotify_get(
            f"https://api.spotify.com/v1/albums?ids={','.join(batch_ids)}&market=BR",
            token,
        )
        if not data:
            break
        for album_full in data.get("albums", []):
            if not album_full:
                continue
            album_name = album_full["name"]
            release_date = album_full.get("release_date", "")
            for t in album_full.get("tracks", {}).get("items", []):
                track_artist_ids = [a["id"] for a in t.get("artists", [])]
                if spotify_artist_id not in track_artist_ids:
                    continue
                if t["id"] not in album_track_map:
                    album_track_map[t["id"]] = {
                        "album_name": album_name,
                        "release_date": release_date,
                    }
                    all_track_ids.append(t["id"])
        time.sleep(0.15)

    # 3. Fetch popularity in batches of 50
    pop_map = {}
    for i in range(0, len(all_track_ids), 50):
        batch = all_track_ids[i:i + 50]
        data = spotify_get(
            f"https://api.spotify.com/v1/tracks?ids={','.join(batch)}&market=BR",
            token,
        )
        if not data:
            break
        for t in data.get("tracks", []):
            if t:
                pop_map[t["id"]] = t
        time.sleep(0.1)

    # 4. Deduplicate by name+duration (keep highest popularity)
    name_map = {}
    for track_id in all_track_ids:
        full = pop_map.get(track_id)
        if not full:
            continue
        album_info = album_track_map[track_id]
        duration = full.get("duration_ms", 0)
        # Chave: nome + duração (tolerância de 2s) para diferenciar versões distintas
        rounded_dur = round(duration / 2000)
        key = (full["name"].lower().strip(), rounded_dur)

        # Detectar feat: artista principal não é o primeiro listado
        track_artist_ids = [a["id"] for a in full.get("artists", [])]
        track_artist_names = [a["name"] for a in full.get("artists", [])]
        is_featured = len(track_artist_ids) > 1 and track_artist_ids[0] != spotify_artist_id

        existing = name_map.get(key)
        if not existing or full.get("popularity", 0) > existing["popularity"]:
            name_map[key] = {
                "artist_name": artist_name,
                "spotify_artist_id": spotify_artist_id,
                "spotify_track_id": full["id"],
                "track_name": full["name"],
                "album_name": album_info["album_name"],
                "release_date": album_info["release_date"],
                "popularity": full.get("popularity", 0),
                "spotify_url": full.get("external_urls", {}).get("spotify", ""),
                "duration_ms": duration,
                "is_featured": is_featured,
                "track_artists": track_artist_names,
            }

    tracks = sorted(name_map.values(), key=lambda t: -t["popularity"])
    return tracks


def sync_artist(artist_name, spotify_artist_id, token):
    """Sync a single artist's discography to Supabase."""
    tracks = fetch_artist_discography(artist_name, spotify_artist_id, token)

    if not tracks:
        print(f"  ⚠️  {artist_name}: 0 tracks retornadas, pulando para não apagar dados")
        return 0

    # Delete old tracks
    sb_delete(f"artist_tracks?artist_name=eq.{requests.utils.quote(artist_name)}")

    # Insert in batches
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(tracks), 100):
        batch = tracks[i:i + 100]
        for t in batch:
            t["synced_at"] = now
        sb_post("artist_tracks", batch)

    # Update artist record
    sb_patch(
        f"artists?name=eq.{requests.utils.quote(artist_name)}",
        {"spotify_id": spotify_artist_id, "discography_synced_at": now},
    )

    return len(tracks)


def main():
    if not all([SUPABASE_URL, SUPABASE_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET]):
        print("❌ Variáveis de ambiente obrigatórias não configuradas")
        sys.exit(1)

    # Prioridade: artistas SEM dados primeiro, depois os já sincronizados (mais antigos primeiro)
    artists_missing = sb_get("artists?select=name,spotify_id&discography_synced_at=is.null&order=name")
    artists_existing = sb_get("artists?select=name,spotify_id&discography_synced_at=not.is.null&order=discography_synced_at.asc")
    artists = artists_missing + artists_existing

    if not artists:
        print("ℹ️  Nenhum artista cadastrado. Nada a fazer.")
        return

    missing_count = len(artists_missing)
    BLOCK_SIZE = 50
    BLOCK_DELAY = 1800  # 30 minutos entre blocos
    ARTIST_DELAY = 2    # 2s entre artistas (normal)
    ARTIST_DELAY_AFTER_LIMIT = 15  # 15s após rate limit leve
    MAX_REQUESTS_PER_BLOCK = 2500  # Limite de requests por bloco para evitar ban

    total = len(artists)
    num_blocks = (total + BLOCK_SIZE - 1) // BLOCK_SIZE

    print(f"\n📀 Atualizando discografia de {total} artistas em {num_blocks} blocos de {BLOCK_SIZE}...")
    print(f"   ➡️  {missing_count} sem dados (prioridade) + {total - missing_count} para atualizar")
    print(f"   ⏱️  Delay: {ARTIST_DELAY}s entre artistas, {BLOCK_DELAY//60}min entre blocos")

    global _request_count, _rate_limit_hits, _hard_limited
    _request_count = 0
    _rate_limit_hits = 0
    _hard_limited = False
    synced = 0
    failed = 0
    skipped = 0
    aborted = False

    for block in range(num_blocks):
        start = block * BLOCK_SIZE
        end = min(start + BLOCK_SIZE, total)
        block_artists = artists[start:end]

        # Pausa entre blocos (não antes do primeiro)
        if block > 0:
            print(f"\n  ⏸️  Pausa de {BLOCK_DELAY // 60} minutos entre blocos...")
            time.sleep(BLOCK_DELAY)

        # Reset hard limit flag no início de cada bloco (nova chance após pausa)
        _hard_limited = False
        block_start_reqs = _request_count

        # Renovar token a cada bloco
        token = get_spotify_token()

        print(f"\n  📦 Bloco {block+1}/{num_blocks} (artistas {start+1}-{end}/{total})")

        for j, a in enumerate(block_artists):
            i = start + j

            # Abortar bloco se recebeu ban temporário
            if _hard_limited:
                print(f"  ⛔ [{i+1}/{total}] {a['name']}: pulando (ban temporário detectado)")
                skipped += 1
                continue

            # Abortar bloco se atingiu limite de requests
            block_reqs = _request_count - block_start_reqs
            if block_reqs >= MAX_REQUESTS_PER_BLOCK:
                print(f"  ⚠️  Limite de {MAX_REQUESTS_PER_BLOCK} requests no bloco atingido, pausando restante")
                _hard_limited = True
                skipped += 1
                continue

            try:
                spotify_id = a.get("spotify_id")

                if not spotify_id:
                    print(f"  🔍 [{i+1}/{total}] Buscando ID do Spotify para {a['name']}...")
                    spotify_id = search_artist_id(a["name"], token)
                    if not spotify_id:
                        print(f"  ⚠️  {a['name']}: não encontrado no Spotify, pulando")
                        skipped += 1
                        time.sleep(0.5)
                        continue

                prev_hits = _rate_limit_hits
                count = sync_artist(a["name"], spotify_id, token)

                if _hard_limited:
                    print(f"  ⛔ [{i+1}/{total}] {a['name']}: abortado por ban temporário")
                    skipped += 1
                    continue

                print(f"  ✅ [{i+1}/{total}] {a['name']}: {count} tracks (reqs: {_request_count}, limits: {_rate_limit_hits})")
                synced += 1

                # Delay adaptativo entre artistas
                if _rate_limit_hits > prev_hits:
                    print(f"    ⏳ Backoff após rate limit: {ARTIST_DELAY_AFTER_LIMIT}s...")
                    time.sleep(ARTIST_DELAY_AFTER_LIMIT)
                else:
                    time.sleep(ARTIST_DELAY)

            except Exception as e:
                failed += 1
                print(f"  ❌ [{i+1}/{total}] {a['name']}: {e}")
                time.sleep(3)

        block_reqs = _request_count - block_start_reqs
        print(f"  📦 Bloco {block+1} concluído! (synced: {synced}, failed: {failed}, skipped: {skipped}, reqs_bloco: {block_reqs})")

        # Se abortou por ban, verificar se vale continuar com próximo bloco
        if _hard_limited and block < num_blocks - 1:
            remaining = total - end
            print(f"  ℹ️  Ban temporário no bloco {block+1}. Próximo bloco em {BLOCK_DELAY//60}min ({remaining} artistas restantes).")

    print(f"\n📀 {synced}/{total} artistas atualizados! ({failed} falhas, {skipped} pulados, {_request_count} requests, {_rate_limit_hits} rate limits)")


if __name__ == "__main__":
    main()
