#!/usr/bin/env python3
"""
Sincroniza discografia de artistas via Spotify API.
Processa artistas sem dados ou desatualizados (7+ dias), respeitando budget de requests.

Uso: python sync_discography.py
Requer: SUPABASE_URL, SUPABASE_SERVICE_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
"""

import os
import sys
import time
import requests
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

MAX_REQUESTS_TOTAL = 4000
RATE_LIMIT_THRESHOLD = 60  # Retry-After acima disso = ban temporário

# ── Supabase helpers ──────────────────────────────────────────────────────────

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


# ── Spotify helpers ───────────────────────────────────────────────────────────

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
_hard_limited = False
_budget_exceeded = False
_last_request_time = 0

MIN_REQUEST_INTERVAL = 0.15  # 150ms entre chamadas


def spotify_get(url, token, max_retries=5):
    """Faz GET na API do Spotify com throttle, retry e controle de budget."""
    global _request_count, _rate_limit_hits, _hard_limited, _budget_exceeded, _last_request_time
    if _hard_limited:
        return None

    for attempt in range(max_retries):
        # Throttle: garantir intervalo mínimo entre requests
        elapsed = time.time() - _last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)

        _request_count += 1
        _last_request_time = time.time()

        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r.status_code == 429:
            _rate_limit_hits += 1
            wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
            if wait > RATE_LIMIT_THRESHOLD:
                print(f"    ❌ Ban temporário (Retry-After: {wait}s) — encerrando")
                _hard_limited = True
                return None
            print(f"    ⏳ Rate limit #{_rate_limit_hits} (req #{_request_count}), aguardando {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()

        # Checar budget após request bem-sucedido
        if _request_count >= MAX_REQUESTS_TOTAL:
            _budget_exceeded = True

        return r.json()
    return None


def search_artist_id(name, token):
    """Busca ID do artista no Spotify por nome."""
    url = f"https://api.spotify.com/v1/search?q={requests.utils.quote(name)}&type=artist&limit=5&market=BR"
    data = spotify_get(url, token)
    if not data:
        return None
    items = data.get("artists", {}).get("items", [])
    for item in items:
        if item["name"].lower() == name.lower():
            return item["id"]
    return items[0]["id"] if items else None


# ── Discografia ───────────────────────────────────────────────────────────────

def fetch_artist_discography(artist_name, spotify_artist_id, token):
    """Busca discografia completa de um artista. Retorna lista de track dicts."""
    # 1. Buscar álbuns: album+single sem limite, appears_on com cap de 150
    albums_own = []
    url = f"https://api.spotify.com/v1/artists/{spotify_artist_id}/albums?include_groups=album,single&limit=50&market=BR"
    while url:
        data = spotify_get(url, token)
        if not data:
            break
        albums_own.extend(data.get("items", []))
        url = data.get("next")

    albums_appears = []
    url = f"https://api.spotify.com/v1/artists/{spotify_artist_id}/albums?include_groups=appears_on&limit=50&market=BR"
    while url and len(albums_appears) < 150:
        data = spotify_get(url, token)
        if not data:
            break
        albums_appears.extend(data.get("items", []))
        url = data.get("next")
    albums_appears = albums_appears[:150]

    albums = albums_own + albums_appears
    # Hard cap total de 300 álbuns
    albums = albums[:300]

    # 2. Buscar tracks via batch album endpoint (20 álbuns por request)
    # Filtrar compilações
    album_track_map = {}
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
            if album_full.get("album_type") == "compilation":
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

    # 3. Buscar popularidade em lotes de 50
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

    # 4. Montar lista de tracks (sem deduplicação — todas as versões)
    tracks = []
    for track_id in all_track_ids:
        full = pop_map.get(track_id)
        if not full:
            continue
        album_info = album_track_map[track_id]
        duration = full.get("duration_ms", 0)
        track_artist_ids = [a["id"] for a in full.get("artists", [])]
        track_artist_names = [a["name"] for a in full.get("artists", [])]
        is_featured = len(track_artist_ids) > 1 and track_artist_ids[0] != spotify_artist_id

        tracks.append({
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
        })

    tracks.sort(key=lambda t: -t["popularity"])
    return tracks


def sync_artist(artist_name, spotify_artist_id, token):
    """Sincroniza discografia de um artista no Supabase."""
    tracks = fetch_artist_discography(artist_name, spotify_artist_id, token)

    if not tracks:
        print(f"  ⚠️  {artist_name}: 0 tracks retornadas, pulando para não apagar dados")
        return 0

    sb_delete(f"artist_tracks?artist_name=eq.{requests.utils.quote(artist_name)}")

    now = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(tracks), 100):
        batch = tracks[i:i + 100]
        for t in batch:
            t["synced_at"] = now
        sb_post("artist_tracks", batch)

    sb_patch(
        f"artists?name=eq.{requests.utils.quote(artist_name)}",
        {"spotify_id": spotify_artist_id, "discography_synced_at": now},
    )

    return len(tracks)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not all([SUPABASE_URL, SUPABASE_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET]):
        print("❌ Variáveis de ambiente obrigatórias não configuradas")
        sys.exit(1)

    # Buscar artistas: sem dados OU 7+ dias desatualizados
    artists = sb_get(
        "artists?select=name,spotify_id"
        "&or=(discography_synced_at.is.null,discography_synced_at.lt.now()-interval'7 days')"  # noqa: E501
        "&order=discography_synced_at.asc.nullsfirst"
    )

    if not artists:
        print("ℹ️  Todos os artistas estão atualizados. Nada a fazer.")
        return

    missing = sum(1 for a in artists if not a.get("spotify_id"))
    total = len(artists)

    print(f"\n📀 {total} artistas para sincronizar (budget: {MAX_REQUESTS_TOTAL} requests)")
    print(f"   ➡️  {missing} sem spotify_id, {total - missing} para atualizar")

    global _request_count, _rate_limit_hits, _hard_limited, _budget_exceeded
    _request_count = 0
    _rate_limit_hits = 0
    _hard_limited = False
    _budget_exceeded = False

    synced = 0
    failed = 0
    skipped = 0
    stop_reason = "lista completa"

    token = get_spotify_token()

    for i, a in enumerate(artists):
        # Checar budget ANTES de iniciar o artista
        if _budget_exceeded:
            stop_reason = f"budget atingido ({_request_count}/{MAX_REQUESTS_TOTAL} requests)"
            break

        if _hard_limited:
            stop_reason = "ban temporário do Spotify"
            break

        try:
            spotify_id = a.get("spotify_id")

            if not spotify_id:
                print(f"  🔍 [{i+1}/{total}] Buscando ID do Spotify para {a['name']}...")
                spotify_id = search_artist_id(a["name"], token)
                if not spotify_id:
                    print(f"  ⚠️  {a['name']}: não encontrado no Spotify, pulando")
                    skipped += 1
                    continue

            if _hard_limited:
                stop_reason = "ban temporário do Spotify"
                break

            count = sync_artist(a["name"], spotify_id, token)

            if _hard_limited:
                stop_reason = "ban temporário do Spotify"
                break

            print(f"  ✅ [{i+1}/{total}] {a['name']}: {count} tracks (reqs: {_request_count})")
            synced += 1

            # Delay entre artistas (curto, throttle já cuida do ritmo)
            time.sleep(0.5)

            # Renovar token se necessário (a cada ~30 min)
            token = get_spotify_token()

        except Exception as e:
            failed += 1
            print(f"  ❌ [{i+1}/{total}] {a['name']}: {e}")
            time.sleep(2)

    # Resumo final
    print(f"\n{'='*60}")
    print(f"📀 Resumo da sincronização")
    print(f"   Artistas sincronizados: {synced}")
    print(f"   Falhas: {failed}")
    print(f"   Pulados (não encontrados): {skipped}")
    print(f"   Requests usados: {_request_count}/{MAX_REQUESTS_TOTAL}")
    print(f"   Rate limits: {_rate_limit_hits}")
    print(f"   Motivo de parada: {stop_reason}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
