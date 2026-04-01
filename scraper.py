#!/usr/bin/env python3
"""
Scraper semanal: Spotify + YouTube Brasil (kworb.net)
Gera ranking combinado por soma de streams
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import re
import time
import os

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RankingBrasilBot/1.0)",
    "Accept-Charset": "utf-8",
}

SPOTIFY_URL = "https://kworb.net/spotify/country/br_weekly.html"
YOUTUBE_URL = "https://kworb.net/youtube/insights/br.html"

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

_token_cache = {"token": None, "expires_at": 0}


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = "utf-8"
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def parse_streams(text):
    cleaned = re.sub(r"[^\d]", "", text.strip())
    return int(cleaned) if cleaned else 0


def get_spotify_token():
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("⚠️  SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET não configurados")
        return None
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        token = data["access_token"]
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
        print(f"🔑 Token Spotify obtido com sucesso (expira em {data.get('expires_in', 3600)}s)")
        return token
    except Exception as e:
        print(f"❌ Falha ao obter token Spotify: {e}")
        return None


def _spotify_get(url, token, params=None, max_retries=3):
    """GET autenticado com tratamento de 429 e backoff exponencial."""
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                print(f"⏳ Rate limited ({url.split('/')[-1].split('?')[0]}), aguardando {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                print(f"⚠️  API error [{url}]: {e}")
                raise
            time.sleep(2 ** attempt)
    return None


def enrich_with_spotify_api(ranking, token):
    """Enriquece o ranking com thumbnails e gêneros via endpoints batch do Spotify."""
    if not token:
        return

    # Fase 1: batch fetch de tracks (thumbnails + artist_ids)
    track_ids = [e["spotify_id"] for e in ranking if e.get("spotify_id")]
    track_data = {}  # spotify_id -> {"thumbnail": str, "artist_id": str}
    print(f"🖼  Buscando thumbnails/artistas para {len(track_ids)} músicas (batch)...")
    for i in range(0, len(track_ids), 50):
        batch = track_ids[i:i + 50]
        try:
            r = _spotify_get(
                "https://api.spotify.com/v1/tracks",
                token,
                {"ids": ",".join(batch), "market": "BR"},
            )
            for track in r.json().get("tracks", []):
                if track:
                    images = track.get("album", {}).get("images", [])
                    thumbnail = images[0]["url"] if images else ""
                    artist_id = track["artists"][0]["id"] if track.get("artists") else ""
                    track_data[track["id"]] = {"thumbnail": thumbnail, "artist_id": artist_id}
        except Exception as e:
            print(f"⚠️  Erro no batch de tracks (i={i}): {e}")
        time.sleep(0.1)

    # Fase 2: batch fetch de artistas (gêneros)
    artist_ids = list({v["artist_id"] for v in track_data.values() if v["artist_id"]})
    artist_genres = {}  # artist_id -> gênero normalizado
    print(f"🎼 Buscando gêneros para {len(artist_ids)} artistas (batch)...")
    for i in range(0, len(artist_ids), 50):
        batch = artist_ids[i:i + 50]
        try:
            r = _spotify_get(
                "https://api.spotify.com/v1/artists",
                token,
                {"ids": ",".join(batch)},
            )
            for artist in r.json().get("artists", []):
                if artist:
                    genres = artist.get("genres", [])
                    artist_genres[artist["id"]] = normalize_genre(genres[0]) if genres else None
        except Exception as e:
            print(f"⚠️  Erro no batch de artistas (i={i}): {e}")
        time.sleep(0.1)

    # Fase 3: aplicar ao ranking
    enriched_thumb = 0
    enriched_genre = 0
    for e in ranking:
        sid = e.get("spotify_id")
        if sid and sid in track_data:
            e["thumbnail_url"] = track_data[sid]["thumbnail"]
            if track_data[sid]["thumbnail"]:
                enriched_thumb += 1
            aid = track_data[sid]["artist_id"]
            if aid and aid in artist_genres and artist_genres[aid]:
                e["genre"] = artist_genres[aid]
                enriched_genre += 1
    print(f"  ✅ {enriched_thumb} thumbnails, {enriched_genre} gêneros via API")


_YT_SUFFIX_RE = re.compile(
    r"\s*[\(\[]\s*(ao vivo|live|acústico|acustico|clipe oficial|official|"
    r"official video|official music video|lyric video|visualizer|"
    r"part\.|feat\.|ft\.)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def _clean_yt_title(title):
    """Remove sufixos comuns de títulos do YouTube para melhorar busca no Spotify."""
    cleaned = _YT_SUFFIX_RE.sub("", title).strip()
    cleaned = re.sub(r"\s*[-–]\s*(ao vivo|live|acústico|acustico)\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or title


def search_spotify_track(artist, title, token):
    """Busca uma faixa no Spotify tentando múltiplas estratégias de query.
    Retorna (spotify_id, spotify_url, thumbnail_url) ou ("", "", "").
    """
    if not token:
        return "", "", ""
    clean_title = _clean_yt_title(title)
    queries = [
        f'artist:"{artist}" track:"{clean_title}"',
        f"{artist} {clean_title}",
        clean_title,
    ]
    for q in queries:
        try:
            r = _spotify_get(
                "https://api.spotify.com/v1/search",
                token,
                {"q": q, "type": "track", "market": "BR", "limit": 1},
            )
            items = r.json().get("tracks", {}).get("items", [])
            if items:
                track = items[0]
                spotify_id = track["id"]
                images = track.get("album", {}).get("images", [])
                thumbnail = images[0]["url"] if images else ""
                return spotify_id, f"https://open.spotify.com/track/{spotify_id}", thumbnail
        except Exception as e:
            print(f"⚠️  Search falhou para '{q}': {e}")
    return "", "", ""


_GENRE_MAP = [
    ("funk", "funk"),
    ("brega", "funk"),
    ("baile funk", "funk"),
    ("sertanejo", "sertanejo"),
    ("pagode", "pagode"),
    ("samba", "pagode"),
    ("forro", "forró"),
    ("forró", "forró"),
    ("xote", "forró"),
    ("baião", "forró"),
    ("axé", "axé"),
    ("axe", "axé"),
    ("gospel", "gospel"),
    ("ccm", "gospel"),
    ("rap", "rap"),
    ("hip hop", "rap"),
    ("trap", "rap"),
    ("mpb", "mpb"),
    ("rock", "rock"),
    ("pop", "pop"),
    ("eletrônica", "eletrônica"),
    ("electronic", "eletrônica"),
    ("dance", "eletrônica"),
]


def normalize_genre(genre_str):
    """Mapeia gênero granular do Spotify para categoria brasileira ampla."""
    g = genre_str.lower()
    for keyword, category in _GENRE_MAP:
        if keyword in g:
            return category
    return "outros"


def guess_genre(artist, title):
    """Infere gênero por palavras-chave no artista/título quando sem dados Spotify."""
    text = (artist + " " + title).lower()
    if re.search(r"\bmc\b|\bmc\.", text) or text.startswith("mc "):
        return "funk"
    if re.search(r"\bdj\b", text) and "sertanejo" not in text:
        return "funk"
    if "sertanejo" in text:
        return "sertanejo"
    if re.search(r"\bpagode\b|\bsamba\b", text):
        return "pagode"
    if re.search(r"\bforró\b|\bforro\b|\bxote\b", text):
        return "forró"
    if re.search(r"\baxé\b|\baxe\b", text):
        return "axé"
    if re.search(r"\bgospel\b|\blouvor\b|\badoração\b", text):
        return "gospel"
    if re.search(r"\brap\b|\brap\b|\bfeat\b", text):
        return "rap"
    return "outros"


def scrape_spotify():
    print("📡 Buscando Spotify BR Weekly...")
    soup = fetch(SPOTIFY_URL)
    tracks = []
    rows = soup.select("table tr")[1:]
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 7:
            continue
        pos = cols[0].get_text(strip=True)
        if not pos.isdigit():
            continue
        cell = cols[2]
        links = cell.find_all("a", href=True)
        track_name = ""
        artist_name = ""
        spotify_id = ""
        for link in links:
            href = link["href"]
            if "/track/" in href:
                track_name = link.get_text(strip=True)
                match = re.search(r"/track/([a-zA-Z0-9]+)\.html", href)
                if match:
                    spotify_id = match.group(1)
            elif "/artist/" in href and not artist_name:
                artist_name = link.get_text(strip=True)
        if not track_name:
            continue
        streams = parse_streams(cols[6].get_text(strip=True))
        spotify_url = f"https://open.spotify.com/track/{spotify_id}" if spotify_id else ""
        tracks.append({
            "pos_spotify": int(pos),
            "artist": artist_name,
            "title": track_name,
            "streams_spotify": streams,
            "spotify_id": spotify_id,
            "spotify_url": spotify_url,
        })
        if int(pos) >= 200:
            break
    print(f"  ✅ {len(tracks)} músicas do Spotify")
    return tracks


def scrape_youtube():
    print("📡 Buscando YouTube BR Weekly...")
    soup = fetch(YOUTUBE_URL)
    tracks = []
    rows = soup.select("table tr")[1:]
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 7:
            continue
        pos = cols[0].get_text(strip=True)
        if not pos.isdigit():
            continue
        full_text = cols[2].get_text(strip=True)
        if " - " in full_text:
            parts = full_text.split(" - ", 1)
            artist_name = parts[0].strip()
            track_name = parts[1].strip()
        else:
            artist_name = ""
            track_name = full_text
        streams = parse_streams(cols[6].get_text(strip=True))
        tracks.append({
            "pos_youtube": int(pos),
            "artist": artist_name,
            "title": track_name,
            "streams_youtube": streams,
        })
        if int(pos) >= 100:
            break
    print(f"  ✅ {len(tracks)} músicas do YouTube")
    return tracks


def normalize(text):
    text = text.lower().strip()
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def match_tracks(spotify_tracks, youtube_tracks):
    print("🔗 Combinando rankings...")
    combined = []
    matched_yt = set()

    for sp in spotify_tracks:
        sp_title = normalize(sp["title"])
        sp_artist = normalize(sp["artist"])
        best_match = None
        best_score = 0

        for i, yt in enumerate(youtube_tracks):
            if i in matched_yt:
                continue
            yt_title = normalize(yt["title"])
            yt_artist = normalize(yt["artist"])
            title_match = sp_title == yt_title or sp_title in yt_title or yt_title in sp_title
            artist_match = sp_artist in yt_artist or yt_artist in sp_artist
            score = (2 if title_match else 0) + (1 if artist_match else 0)
            if score >= 2 and score > best_score:
                best_score = score
                best_match = (i, yt)

        entry = {
            "artist": sp["artist"],
            "title": sp["title"],
            "spotify_url": sp["spotify_url"],
            "spotify_id": sp["spotify_id"],
            "pos_spotify": sp["pos_spotify"],
            "streams_spotify": sp["streams_spotify"],
            "pos_youtube": None,
            "streams_youtube": 0,
            "in_both": False,
        }

        if best_match:
            idx, yt = best_match
            matched_yt.add(idx)
            entry["pos_youtube"] = yt["pos_youtube"]
            entry["streams_youtube"] = yt["streams_youtube"]
            entry["in_both"] = True

        entry["total_streams"] = entry["streams_spotify"] + entry["streams_youtube"]
        combined.append(entry)

    for i, yt in enumerate(youtube_tracks):
        if i not in matched_yt:
            combined.append({
                "artist": yt["artist"],
                "title": yt["title"],
                "spotify_url": "",
                "spotify_id": "",
                "pos_spotify": None,
                "streams_spotify": 0,
                "pos_youtube": yt["pos_youtube"],
                "streams_youtube": yt["streams_youtube"],
                "in_both": False,
                "total_streams": yt["streams_youtube"],
            })

    combined.sort(key=lambda x: x["total_streams"], reverse=True)
    for i, e in enumerate(combined):
        e["rank"] = i + 1

    in_both = sum(1 for e in combined if e["in_both"])
    print(f"  ✅ {in_both} músicas em ambas as plataformas")
    return combined


def run():
    print(f"\n🎵 Ranking Brasil Semanal — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
    os.makedirs("data", exist_ok=True)
    spotify_tracks = scrape_spotify()
    time.sleep(2)
    youtube_tracks = scrape_youtube()
    ranking = match_tracks(spotify_tracks, youtube_tracks)

    token = get_spotify_token()
    if not token:
        print("⚠️  Sem credenciais Spotify — thumbnails e gêneros serão limitados")

    # Passo 5: buscar Spotify para tracks só no YouTube
    yt_only_tracks = [e for e in ranking if not e["in_both"] and e["pos_spotify"] is None]
    if token and yt_only_tracks:
        print(f"🔍 Buscando links Spotify para {len(yt_only_tracks)} músicas só no YouTube...")
        for e in yt_only_tracks:
            spotify_id, spotify_url, thumbnail_url = search_spotify_track(
                e["artist"], e["title"], token
            )
            e["spotify_id"] = spotify_id
            e["spotify_url"] = spotify_url
            e["thumbnail_url"] = thumbnail_url
    else:
        for e in yt_only_tracks:
            e.setdefault("thumbnail_url", "")

    # Passo 6: enriquecer com thumbnails e gêneros via batch API
    enrich_with_spotify_api(ranking, token)

    # Garantir thumbnail_url em todos os entries
    for e in ranking:
        e.setdefault("thumbnail_url", "")

    # Fallback: usar palavras-chave para tracks sem gênero da API
    for e in ranking:
        if not e.get("genre"):
            e["genre"] = guess_genre(e.get("artist", ""), e.get("title", ""))

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "week_label": f"Semana de {datetime.now().strftime('%d/%m/%Y')}",
        "tracks": ranking,
    }
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ data/ranking.json gerado — {len(ranking)} músicas")
    if ranking:
        print(f"🥇 #1: {ranking[0]['artist']} — {ranking[0]['title']} ({ranking[0]['total_streams']:,} streams)")


if __name__ == "__main__":
    run()
