#!/usr/bin/env python3
"""
Gerenciamento de playlists Spotify baseado no ranking semanal.
Cria e sincroniza playlists por gênero + playlist especial "Mais Tocadas".
"""

import json
import os
import time
import requests

PLAYLIST_IDS_PATH = "data/playlist_ids.json"

# Gêneros que compõem a playlist "Mais Tocadas"
MAIS_TOCADAS_GENRES = {"funk", "forró/piseiro", "pagode", "sertanejo"}

SPOTIFY_API = "https://api.spotify.com/v1"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _spotify_request(method, url, token, json_data=None, max_retries=3):
    """Faz request à API do Spotify com retry em rate limit."""
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(max_retries):
        try:
            r = requests.request(
                method, url, headers=headers, json=json_data, timeout=10
            )
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                print(f"  ⏳ Rate limited, aguardando {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"  ⚠️  Tentativa {attempt + 1} falhou: {e}")
            time.sleep(1)
    return None


def _load_playlist_ids():
    """Carrega mapeamento gênero → playlist_id do cache local."""
    if os.path.exists(PLAYLIST_IDS_PATH):
        with open(PLAYLIST_IDS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_playlist_ids(mapping):
    """Salva mapeamento gênero → playlist_id no cache local."""
    os.makedirs(os.path.dirname(PLAYLIST_IDS_PATH), exist_ok=True)
    with open(PLAYLIST_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def _get_user_id(token):
    """Obtém o user_id do perfil autenticado."""
    r = _spotify_request("GET", f"{SPOTIFY_API}/me", token)
    return r.json()["id"]


# ── Playlist CRUD ────────────────────────────────────────────────────────────

def _get_all_user_playlists(token, user_id):
    """Retorna todas as playlists do usuário (paginado)."""
    playlists = []
    url = f"{SPOTIFY_API}/me/playlists?limit=50"
    while url:
        r = _spotify_request("GET", url, token)
        data = r.json()
        for p in data.get("items", []):
            if p and p.get("owner", {}).get("id") == user_id:
                playlists.append(p)
        url = data.get("next")
    return playlists


def get_or_create_playlist(token, user_id, name, description=""):
    """Busca playlist pelo nome exato ou cria uma nova (pública)."""
    # Verificar cache local primeiro
    mapping = _load_playlist_ids()
    cached_id = mapping.get(name)
    if cached_id:
        # Verificar se a playlist ainda existe
        try:
            r = _spotify_request("GET", f"{SPOTIFY_API}/playlists/{cached_id}?fields=id,name", token)
            if r and r.status_code == 200:
                return cached_id
        except Exception:
            pass  # playlist pode ter sido deletada, continuar buscando

    # Buscar nas playlists do usuário
    user_playlists = _get_all_user_playlists(token, user_id)
    for p in user_playlists:
        if p["name"] == name:
            mapping[name] = p["id"]
            _save_playlist_ids(mapping)
            return p["id"]

    # Criar nova playlist
    r = _spotify_request(
        "POST",
        f"{SPOTIFY_API}/users/{user_id}/playlists",
        token,
        json_data={
            "name": name,
            "public": True,
            "description": description,
        },
    )
    playlist_id = r.json()["id"]
    mapping[name] = playlist_id
    _save_playlist_ids(mapping)
    print(f"  ✨ Playlist criada: {name} ({playlist_id})")
    return playlist_id


# ── Playlist sync ────────────────────────────────────────────────────────────

def _get_playlist_track_uris(token, playlist_id):
    """Retorna lista ordenada de URIs da playlist atual."""
    uris = []
    url = f"{SPOTIFY_API}/playlists/{playlist_id}/tracks?fields=items(track(uri)),next&limit=100"
    while url:
        r = _spotify_request("GET", url, token)
        data = r.json()
        for item in data.get("items", []):
            track = item.get("track")
            if track and track.get("uri"):
                uris.append(track["uri"])
        url = data.get("next")
    return uris


def sync_genre_playlist(token, playlist_id, new_tracks, max_tracks=101):
    """
    Sincroniza playlist com os tracks do ranking.

    - Tracks do ranking são colocados no topo, na ordem do ranking
    - Tracks que saíram do ranking permanecem após os do ranking
    - Se total > max_tracks, remove os excedentes (tracks antigos que saíram)
    """
    # URIs dos novos tracks (ranking atual), filtrar sem spotify_id
    new_uris = []
    for t in new_tracks:
        sid = t.get("spotify_id")
        if sid:
            new_uris.append(f"spotify:track:{sid}")

    # URIs atuais na playlist
    current_uris = _get_playlist_track_uris(token, playlist_id)

    # Tracks antigos que não estão no ranking atual (manter no final)
    new_uris_set = set(new_uris)
    old_remaining = [uri for uri in current_uris if uri not in new_uris_set]

    # Montar lista final: ranking no topo + antigos no final
    final_uris = new_uris + old_remaining

    # Limitar a max_tracks (cortando os antigos mais velhos)
    if len(final_uris) > max_tracks:
        final_uris = final_uris[:max_tracks]

    # Remover duplicatas mantendo ordem
    seen = set()
    deduped = []
    for uri in final_uris:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)
    final_uris = deduped

    # Se não mudou nada, skip
    if final_uris == current_uris:
        return 0

    # Substituir toda a playlist de uma vez (PUT replace)
    # PUT aceita no máximo 100 URIs por chamada
    if len(final_uris) <= 100:
        _spotify_request(
            "PUT",
            f"{SPOTIFY_API}/playlists/{playlist_id}/tracks",
            token,
            json_data={"uris": final_uris},
        )
    else:
        # Primeiro PUT com os primeiros 100
        _spotify_request(
            "PUT",
            f"{SPOTIFY_API}/playlists/{playlist_id}/tracks",
            token,
            json_data={"uris": final_uris[:100]},
        )
        # POST para adicionar o restante (em batches de 100)
        for i in range(100, len(final_uris), 100):
            batch = final_uris[i:i + 100]
            _spotify_request(
                "POST",
                f"{SPOTIFY_API}/playlists/{playlist_id}/tracks",
                token,
                json_data={"uris": batch},
            )

    added = len(new_uris_set - set(current_uris))
    return added


# ── Orquestração ─────────────────────────────────────────────────────────────

def sync_all_playlists(token, ranking_tracks):
    """
    Sincroniza todas as playlists baseado no ranking atual.
    Cria playlists por gênero + playlist especial "Mais Tocadas".
    """
    print("\n🎶 Sincronizando playlists Spotify...")

    user_id = _get_user_id(token)
    print(f"  👤 Usuário: {user_id}")

    # Agrupar tracks por gênero (multi-gênero: track aparece em todas as playlists)
    genres = {}
    for track in ranking_tracks:
        track_genres = track.get("_genres") or [track.get("genre", "outros")]
        for genre in track_genres:
            genre_key = genre.lower().strip()
            if genre_key not in genres:
                genres[genre_key] = {"display_name": genre, "tracks": []}
            genres[genre_key]["tracks"].append(track)

    # Sincronizar playlist por gênero
    total_synced = 0
    for genre_key, genre_data in sorted(genres.items()):
        display_name = genre_data["display_name"]
        tracks = genre_data["tracks"]
        playlist_name = f"RankingBR — {display_name}"

        playlist_id = get_or_create_playlist(
            token, user_id, playlist_name,
            description=f"Top músicas de {display_name} no Brasil — atualizado semanalmente pelo RankingBR",
        )

        added = sync_genre_playlist(token, playlist_id, tracks)
        total_synced += 1
        status = f"+{added} novas" if added else "atualizada"
        print(f"  ✅ {playlist_name}: {len(tracks)} tracks ({status})")
        time.sleep(0.2)  # gentileza com a API

    # Playlist especial "Mais Tocadas"
    mais_tocadas_tracks = [
        t for t in ranking_tracks
        if any(g.lower().strip() in MAIS_TOCADAS_GENRES
               for g in (t.get("_genres") or [t.get("genre", "")]))
    ]
    # Já vem ordenado pelo rank geral
    mais_tocadas_tracks.sort(key=lambda t: t.get("rank", 9999))

    playlist_name = "RankingBR — Mais Tocadas"
    playlist_id = get_or_create_playlist(
        token, user_id, playlist_name,
        description="Top Funk, Forró/Piseiro, Pagode e Sertanejo no Brasil — atualizado semanalmente pelo RankingBR",
    )
    added = sync_genre_playlist(token, playlist_id, mais_tocadas_tracks, max_tracks=150)
    status = f"+{added} novas" if added else "atualizada"
    print(f"  ✅ {playlist_name}: {len(mais_tocadas_tracks)} tracks ({status})")

    total_synced += 1
    print(f"\n🎶 {total_synced} playlists sincronizadas!")
