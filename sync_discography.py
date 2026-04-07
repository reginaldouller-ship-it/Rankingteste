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


def spotify_get(url, token, max_retries=3):
    for attempt in range(max_retries):
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
            print(f"    ⏳ Rate limited, aguardando {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    return None


def fetch_artist_discography(artist_name, spotify_artist_id, token):
    """Fetch complete discography for an artist. Returns list of track dicts."""
    # 1. Get all albums
    albums = []
    url = f"https://api.spotify.com/v1/artists/{spotify_artist_id}/albums?include_groups=album,single,appears_on,compilation&limit=50&market=BR"
    while url:
        data = spotify_get(url, token)
        albums.extend(data.get("items", []))
        url = data.get("next")

    # 2. Get tracks from each album
    album_track_map = {}  # track_id -> {album_name, release_date}
    all_track_ids = []
    for album in albums:
        url = f"https://api.spotify.com/v1/albums/{album['id']}/tracks?limit=50&market=BR"
        while url:
            data = spotify_get(url, token)
            for t in data.get("items", []):
                if t["id"] not in album_track_map:
                    album_track_map[t["id"]] = {
                        "album_name": album["name"],
                        "release_date": album.get("release_date", ""),
                    }
                    all_track_ids.append(t["id"])
            url = data.get("next")

    # 3. Fetch popularity in batches of 50
    pop_map = {}
    for i in range(0, len(all_track_ids), 50):
        batch = all_track_ids[i:i + 50]
        data = spotify_get(
            f"https://api.spotify.com/v1/tracks?ids={','.join(batch)}&market=BR",
            token,
        )
        for t in data.get("tracks", []):
            if t:
                pop_map[t["id"]] = t

    # 4. Deduplicate by name (keep highest popularity)
    name_map = {}
    for track_id in all_track_ids:
        full = pop_map.get(track_id)
        if not full:
            continue
        album_info = album_track_map[track_id]
        key = full["name"].lower().strip()
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
                "duration_ms": full.get("duration_ms", 0),
            }

    tracks = sorted(name_map.values(), key=lambda t: -t["popularity"])
    return tracks


def sync_artist(artist_name, spotify_artist_id, token):
    """Sync a single artist's discography to Supabase."""
    tracks = fetch_artist_discography(artist_name, spotify_artist_id, token)

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

    # Get all artists that have been synced at least once
    artists = sb_get(
        "artists?select=name,spotify_id&discography_synced_at=not.is.null&spotify_id=not.is.null"
    )

    if not artists:
        print("ℹ️  Nenhum artista com discografia sincronizada. Nada a fazer.")
        return

    print(f"\n📀 Atualizando discografia de {len(artists)} artistas...")
    token = get_spotify_token()

    synced = 0
    for a in artists:
        try:
            count = sync_artist(a["name"], a["spotify_id"], token)
            print(f"  ✅ {a['name']}: {count} tracks")
            synced += 1
            time.sleep(0.5)  # rate limit courtesy
        except Exception as e:
            print(f"  ❌ {a['name']}: {e}")

    print(f"\n📀 {synced}/{len(artists)} artistas atualizados!")


if __name__ == "__main__":
    main()
