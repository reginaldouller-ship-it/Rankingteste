#!/usr/bin/env python3
"""
Sincroniza playlists Spotify com o ranking atual do Supabase.
Lê os tracks da semana mais recente, resolve gêneros (artist_genres + track_overrides),
e chama sync_all_playlists.

Uso: python sync_playlists_runner.py
Requer: SUPABASE_URL, SUPABASE_SERVICE_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
"""

import os
import sys
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def sb_get(path):
    """GET no Supabase REST API."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def load_ranking_with_genres():
    """Carrega ranking da semana mais recente com gêneros resolvidos."""
    # 1. Buscar semana mais recente
    weeks = sb_get("ranking_weeks?select=id,week_label&order=id.desc&limit=1")
    if not weeks:
        print("❌ Nenhuma semana encontrada no Supabase")
        sys.exit(1)

    week_id = weeks[0]["id"]
    week_label = weeks[0]["week_label"]
    print(f"📅 Semana: {week_label} (id={week_id})")

    # 2. Buscar tracks da semana
    tracks = sb_get(f"ranking_tracks?week_id=eq.{week_id}&select=*&order=rank")
    print(f"🎵 {len(tracks)} tracks carregados")

    # 3. Buscar mapeamento artista → gêneros
    artist_genres_rows = sb_get("artists_with_genres?select=name,genres")
    artist_genres = {}
    for row in artist_genres_rows:
        if row.get("name") and row.get("genres"):
            artist_genres[row["name"].lower()] = row["genres"]

    # 4. Buscar track overrides
    overrides_rows = sb_get("track_overrides_with_genres?select=spotify_id,genre_name")
    track_overrides = {}
    for row in overrides_rows:
        if row.get("spotify_id") and row.get("genre_name"):
            track_overrides[row["spotify_id"]] = row["genre_name"]

    # 5. Resolver gênero de cada track
    for t in tracks:
        # Track override tem prioridade
        if t.get("spotify_id") and t["spotify_id"] in track_overrides:
            t["genre"] = track_overrides[t["spotify_id"]]
            continue

        # Gênero do artista
        artist_name = (t.get("artist") or "").lower()
        if artist_name in artist_genres and artist_genres[artist_name]:
            t["genre"] = artist_genres[artist_name][0]
        elif not t.get("genre"):
            t["genre"] = "outros"

    return tracks


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ SUPABASE_URL e SUPABASE_SERVICE_KEY são obrigatórios")
        sys.exit(1)

    # Importar scraper para obter token Spotify
    from scraper import get_spotify_user_token, SPOTIFY_REFRESH_TOKEN

    if not SPOTIFY_REFRESH_TOKEN:
        print("❌ SPOTIFY_REFRESH_TOKEN não configurado")
        sys.exit(1)

    # Carregar ranking com gêneros
    tracks = load_ranking_with_genres()

    # Obter token Spotify (user scope)
    user_token = get_spotify_user_token()
    if not user_token:
        print("❌ Falha ao obter token Spotify")
        sys.exit(1)

    # Sincronizar playlists
    from spotify_playlists import sync_all_playlists
    sync_all_playlists(user_token, tracks)

    print("\n✅ Sincronização concluída!")


if __name__ == "__main__":
    main()
