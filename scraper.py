#!/usr/bin/env python3
"""
Scraper semanal: Spotify + YouTube Brasil (kworb.net)
Gera ranking combinado por soma de streams e persiste no Supabase.
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone, timedelta
import re
import time
import os
import unicodedata
from collections import Counter

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RankingBrasilBot/1.0)",
    "Accept-Charset": "utf-8",
}

SPOTIFY_URL = "https://kworb.net/spotify/country/br_weekly.html"
YOUTUBE_URL = "https://kworb.net/youtube/insights/br.html"

SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SUPABASE_URL          = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")
SPOTIFY_REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")

_token_cache = {"token": None, "expires_at": 0}
_user_token_cache = {"token": None, "expires_at": 0}

# Regex para split de múltiplos artistas em títulos do YouTube
# Faz split em: vírgula, "feat.", "ft."
# NÃO faz split em "&" nem "e" — preserva duplas como "Henrique & Juliano", "Felipe e Rodrigo"
_FEAT_RE = re.compile(
    r'\s+(?:feat\.?|ft\.?)\s+|\s*,\s*(?=\S)',
    re.IGNORECASE,
)


# ── Supabase ──────────────────────────────────────────────────────────────────

def get_supabase():
    """Retorna cliente Supabase (service role) ou None se não configurado."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except ImportError:
        print("⚠️  Pacote 'supabase' não instalado — pulando persistência no banco")
        return None
    except Exception as e:
        print(f"⚠️  Falha ao conectar ao Supabase: {e}")
        return None


def _sb_load_genres_config(sb):
    """Carrega config de gêneros do Supabase."""
    # Artistas com gêneros (via view)
    res = sb.table("artists_with_genres").select("name,genres").execute()
    artist_genres = {row["name"]: row["genres"] for row in res.data}

    # Overrides por track (view agora retorna array de genre_names)
    ov_res = sb.table("track_overrides_with_genres").select("*").execute()
    track_overrides = {row["spotify_id"]: row["genre_names"] for row in ov_res.data}

    # Lista de gêneros
    g_res = sb.table("genres").select("name").order("name").execute()
    genres = [row["name"] for row in g_res.data]

    return {"genres": genres, "artist_genres": artist_genres, "track_overrides": track_overrides}


def _sb_load_history(sb):
    """Carrega histórico de tracks do Supabase."""
    res = sb.table("track_history").select("*").execute()
    seen = {
        row["track_key"]: {
            "first_seen": row["first_seen"],
            "last_seen":  row["last_seen"],
            "appearances": row["appearances"],
        }
        for row in res.data
    }
    return {"seen_tracks": seen}


def _sb_update_history(sb, history):
    """Sincroniza histórico com Supabase via upsert em lotes."""
    rows = [
        {
            "track_key":   key,
            "first_seen":  v["first_seen"],
            "last_seen":   v["last_seen"],
            "appearances": v["appearances"],
        }
        for key, v in history["seen_tracks"].items()
    ]
    for i in range(0, len(rows), 500):
        sb.table("track_history").upsert(rows[i:i + 500], on_conflict="track_key").execute()
    print(f"  ✅ Histórico sincronizado ({len(rows)} tracks únicos)")


def _sb_upsert_artists(sb, ranking):
    """Upsert de todos os artistas do ranking com track_count atualizado."""
    counts: dict[str, int] = {}
    for e in ranking:
        for a in e.get("artists") or [e["artist"]]:
            if a:
                counts[a] = counts.get(a, 0) + 1
    rows = [{"name": name, "track_count": cnt} for name, cnt in counts.items()]
    for i in range(0, len(rows), 100):
        sb.table("artists").upsert(rows[i:i + 100], on_conflict="name").execute()
    print(f"  ✅ {len(rows)} artistas sincronizados")


def _sb_save_ranking(sb, ranking, week_label, week_end_date=None):
    """Salva a semana e todos os tracks no Supabase."""
    row = {
        "week_label":   week_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if week_end_date:
        row["week_end_date"] = week_end_date
    week_res = sb.table("ranking_weeks").insert(row).execute()
    week_id = week_res.data[0]["id"]

    track_rows = [
        {
            "week_id":         week_id,
            "rank":            e["rank"],
            "artist":          e["artist"],
            "artists":         e.get("artists") or [e["artist"]],
            "title":           e["title"],
            "spotify_id":      e.get("spotify_id", ""),
            "spotify_url":     e.get("spotify_url", ""),
            "pos_spotify":     e.get("pos_spotify"),
            "streams_spotify": e.get("streams_spotify", 0),
            "pos_youtube":     e.get("pos_youtube"),
            "streams_youtube": e.get("streams_youtube", 0),
            "in_both":         e.get("in_both", False),
            "total_streams":   e.get("total_streams", 0),
            "thumbnail_url":   e.get("thumbnail_url", ""),
            "genre":           e.get("genre"),
            "trend":           e.get("trend"),
            "prev_rank":       e.get("prev_rank"),
        }
        for e in ranking
    ]
    for i in range(0, len(track_rows), 100):
        sb.table("ranking_tracks").insert(track_rows[i:i + 100]).execute()

    print(f"  ✅ Ranking salvo no Supabase (week_id={week_id}, {len(track_rows)} tracks)")
    return week_id


# ── Spotify auth ──────────────────────────────────────────────────────────────

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
        print(f"🔑 Token Spotify obtido (expira em {data.get('expires_in', 3600)}s)")
        return token
    except Exception as e:
        print(f"❌ Falha ao obter token Spotify: {e}")
        return None


def get_spotify_user_token(refresh_token=None):
    """Obtém access_token via refresh_token (OAuth user scope, para playlists)."""
    refresh_token = refresh_token or SPOTIFY_REFRESH_TOKEN
    if _user_token_cache["token"] and time.time() < _user_token_cache["expires_at"]:
        return _user_token_cache["token"]
    if not refresh_token or not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        token = data["access_token"]
        _user_token_cache["token"] = token
        _user_token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
        print(f"🔑 Token Spotify (user) obtido (expira em {data.get('expires_in', 3600)}s)")
        return token
    except Exception as e:
        print(f"❌ Falha ao obter token Spotify (user): {e}")
        return None


def _spotify_get(url, token, params=None, max_retries=3):
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                print(f"⏳ Rate limited, aguardando {wait}s...")
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


# ── Spotify API enrichment ────────────────────────────────────────────────────

def enrich_with_spotify_api(ranking, token):
    """Enriquece o ranking com thumbnails via batch Spotify.
    Retorna dict {artist_id -> genre_normalizado} para resolve_genre().
    """
    api_artist_genres: dict[str, str] = {}
    if not token:
        return api_artist_genres

    track_ids = [e["spotify_id"] for e in ranking if e.get("spotify_id")]
    track_data: dict[str, dict] = {}

    print(f"🖼  Buscando thumbnails para {len(track_ids)} músicas...")
    for i in range(0, len(track_ids), 50):
        batch = track_ids[i:i + 50]
        try:
            r = _spotify_get(
                "https://api.spotify.com/v1/tracks",
                token,
                {"ids": ",".join(batch), "market": "BR"},
            )
            if not r:
                continue
            for track in r.json().get("tracks", []):
                if track:
                    images = track.get("album", {}).get("images", [])
                    thumbnail = images[0]["url"] if images else ""
                    artist_ids_all = [a["id"] for a in track.get("artists", []) if a.get("id")]
                    track_data[track["id"]] = {
                        "thumbnail": thumbnail,
                        "artist_ids": artist_ids_all,
                    }
        except Exception as e:
            print(f"⚠️  Erro no batch de tracks (i={i}): {e}")
        time.sleep(0.1)

    all_artist_ids = list({
        aid
        for v in track_data.values()
        for aid in v["artist_ids"]
    })
    print(f"🎼 Buscando gêneros para {len(all_artist_ids)} artistas...")
    for i in range(0, len(all_artist_ids), 50):
        batch = all_artist_ids[i:i + 50]
        try:
            r = _spotify_get(
                "https://api.spotify.com/v1/artists",
                token,
                {"ids": ",".join(batch)},
            )
            if not r:
                continue
            for artist in r.json().get("artists", []):
                if artist:
                    genres = artist.get("genres", [])
                    api_artist_genres[artist["id"]] = normalize_genre(genres[0]) if genres else None
        except Exception as e:
            print(f"⚠️  Erro no batch de artistas (i={i}): {e}")
        time.sleep(0.1)

    enriched = 0
    for e in ranking:
        sid = e.get("spotify_id")
        if sid and sid in track_data:
            # FIX: não sobrescreve thumbnail existente com string vazia
            new_thumb = track_data[sid]["thumbnail"]
            if new_thumb:
                e["thumbnail_url"] = new_thumb
                enriched += 1
            e["_api_artist_ids"] = track_data[sid]["artist_ids"]

    print(f"  ✅ {enriched} thumbnails via API")
    return api_artist_genres


_YT_SUFFIX_RE = re.compile(
    r"\s*[\(\[]\s*(ao vivo|en vivo|live|acústico|acustico|clipe oficial|official|"
    r"official video|official music video|lyric video|visualizer|"
    r"part\.|feat\.|ft\.)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def _clean_yt_title(title):
    cleaned = _YT_SUFFIX_RE.sub("", title).strip()
    cleaned = re.sub(r"\s*[-–]\s*(ao vivo|live|acústico|acustico)\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or title


def _artist_matches(expected_artist, spotify_track):
    """Verifica se ao menos um artista do resultado Spotify bate com o artista esperado."""
    expected = expected_artist.lower()
    sp_artists = [a["name"].lower() for a in spotify_track.get("artists", [])]
    for sp in sp_artists:
        # Match direto ou parcial (um contém o outro)
        if sp in expected or expected in sp:
            return True
        # Match por primeira palavra (ex: "Henrique" em "Henrique & Juliano")
        sp_first = sp.split()[0] if sp.split() else sp
        exp_first = expected.split()[0] if expected.split() else expected
        if sp_first == exp_first:
            return True
    return False


def search_spotify_track(artist, title, token):
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
                {"q": q, "type": "track", "market": "BR", "limit": 5},
            )
            items = r.json().get("tracks", {}).get("items", [])
            # Filtrar por artista e pegar a versão mais popular
            matching = [t for t in items if _artist_matches(artist, t)]
            if matching:
                best = max(matching, key=lambda t: t.get("popularity", 0))
                spotify_id = best["id"]
                images = best.get("album", {}).get("images", [])
                thumbnail = images[0]["url"] if images else ""
                return spotify_id, f"https://open.spotify.com/track/{spotify_id}", thumbnail
        except Exception as e:
            print(f"⚠️  Search falhou para '{q}': {e}")
    return "", "", ""


# ── Gêneros ───────────────────────────────────────────────────────────────────

_GENRE_MAP = [
    ("funk", "funk"), ("brega", "funk"), ("baile funk", "funk"),
    ("sertanejo", "sertanejo"),
    ("pagode", "pagode"), ("samba", "pagode"),
    ("forro", "forró"), ("forró", "forró"), ("xote", "forró"), ("baião", "forró"),
    ("axé", "axé"), ("axe", "axé"),
    ("gospel", "gospel"), ("ccm", "gospel"),
    ("rap", "rap"), ("hip hop", "rap"), ("trap", "rap"),
    ("mpb", "mpb"),
    ("rock", "rock"),
    ("pop", "pop"),
    ("eletrônica", "eletrônica"), ("electronic", "eletrônica"), ("dance", "eletrônica"),
]


def normalize_genre(genre_str):
    g = genre_str.lower()
    for keyword, category in _GENRE_MAP:
        if keyword in g:
            return category
    return "outros"


def guess_genre(artist, title):
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
    if re.search(r"\brap\b|\bfeat\b", text):
        return "rap"
    return "outros"


def load_genres_config(sb=None):
    """Carrega config de gêneros. Tenta Supabase primeiro, fallback para JSON."""
    if sb:
        try:
            return _sb_load_genres_config(sb)
        except Exception as e:
            print(f"⚠️  Falha ao carregar gêneros do Supabase: {e}")
    # Fallback: arquivo local
    try:
        with open("data/genres.json", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"genres": [], "artist_genres": {}, "track_overrides": {}}


def resolve_genres(entry, artist_genres_map, track_overrides, api_artist_genres):
    """Resolve gêneros de um track (retorna lista).
    Cadeia de prioridade:
    1. Override manual por track (spotify_id) — retorna lista de gêneros
    2. Gêneros dos artistas (union de todos)
    3. Gênero da API Spotify (artist_ids)
    4. guess_genre() por palavras-chave
    """
    spotify_id = entry.get("spotify_id", "")
    if spotify_id and spotify_id in track_overrides:
        ov = track_overrides[spotify_id]
        return ov if isinstance(ov, list) else [ov]

    artists = [a for a in (entry.get("artists") or [entry.get("artist", "")]) if a]

    # Collect genres from all artists
    genre_set = set()
    for a in artists:
        a_genres = artist_genres_map.get(a, [])
        genre_set.update(a_genres)
    if genre_set:
        return sorted(genre_set)

    for aid in entry.get("_api_artist_ids", []):
        g = api_artist_genres.get(aid)
        if g:
            return [g]

    return [guess_genre(entry.get("artist", ""), entry.get("title", ""))]


def resolve_genre(entry, artist_genres_map, track_overrides, api_artist_genres):
    """Backward compat — returns first genre."""
    return resolve_genres(entry, artist_genres_map, track_overrides, api_artist_genres)[0]


def normalize_artist_name(name):
    """Normaliza nome de artista: Unicode NFC + strip.
    Evita duplicatas como 'Mc Jacaré' (NFD) vs 'Mc Jacaré' (NFC).
    """
    return unicodedata.normalize("NFC", name.strip())


# ── Histórico ─────────────────────────────────────────────────────────────────

def normalize(text):
    text = text.lower().strip()
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _track_key(artist, title):
    return normalize(artist) + "|" + normalize(title)


def load_history(sb=None):
    if sb:
        try:
            return _sb_load_history(sb)
        except Exception as e:
            print(f"⚠️  Falha ao carregar histórico do Supabase: {e}")
    try:
        with open("data/ranking_history.json", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"seen_tracks": {}}


def update_history(ranking, history, sb=None):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for e in ranking:
        key = _track_key(e["artist"], e["title"])
        if key not in history["seen_tracks"]:
            history["seen_tracks"][key] = {"first_seen": today, "appearances": 0}
        history["seen_tracks"][key]["last_seen"] = today
        history["seen_tracks"][key]["appearances"] += 1

    if sb:
        try:
            _sb_update_history(sb, history)
        except Exception as e:
            print(f"⚠️  Falha ao sincronizar histórico: {e}")

    # Backup local sempre
    os.makedirs("data", exist_ok=True)
    with open("data/ranking_history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ── Scrapers ──────────────────────────────────────────────────────────────────

def extract_week_date(soup, source="spotify"):
    """Extrai a data 'week ending' do cabeçalho da página kworb.
    Spotify: 'Spotify Weekly Chart - Brazil - 2026/04/02'
    YouTube: 'YouTube Brazil - Week ending 2026/04/02'
    Retorna string 'YYYY-MM-DD' ou None.
    """
    text = soup.get_text()
    m = re.search(r'(\d{4}/\d{2}/\d{2})', text)
    if m:
        date_str = m.group(1).replace("/", "-")
        print(f"  📅 {source} week ending: {date_str}")
        return date_str
    print(f"  ⚠️ Não foi possível extrair data da semana ({source})")
    return None


def scrape_spotify():
    print("📡 Buscando Spotify BR Weekly...")
    soup = fetch(SPOTIFY_URL)
    week_date = extract_week_date(soup, "Spotify")
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
        artist_names: list[str] = []
        spotify_id = ""
        for link in links:
            href = link["href"]
            if "/track/" in href:
                track_name = link.get_text(strip=True)
                m = re.search(r"/track/([a-zA-Z0-9]+)\.html", href)
                if m:
                    spotify_id = m.group(1)
            elif "/artist/" in href:
                artist_names.append(normalize_artist_name(link.get_text(strip=True)))
        if not track_name:
            continue
        streams = parse_streams(cols[6].get_text(strip=True))
        artist_name = artist_names[0] if artist_names else ""
        spotify_url = f"https://open.spotify.com/track/{spotify_id}" if spotify_id else ""
        tracks.append({
            "pos_spotify": int(pos),
            "artist": artist_name,
            "artists": artist_names,
            "title": track_name,
            "streams_spotify": streams,
            "spotify_id": spotify_id,
            "spotify_url": spotify_url,
        })
        if int(pos) >= 200:
            break
    print(f"  ✅ {len(tracks)} músicas do Spotify")
    return tracks, week_date


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
            artist_raw = parts[0].strip()
            track_name = parts[1].strip()
            artist_parts = [normalize_artist_name(a) for a in _FEAT_RE.split(artist_raw) if a.strip()]
            artist_names = artist_parts if artist_parts else [normalize_artist_name(artist_raw)]
            artist_name = artist_names[0]
        else:
            artist_name = ""
            artist_names = []
            track_name = full_text
        streams = parse_streams(cols[6].get_text(strip=True))
        tracks.append({
            "pos_youtube": int(pos),
            "artist": artist_name,
            "artists": artist_names,
            "title": track_name,
            "streams_youtube": streams,
        })
        if int(pos) >= 100:
            break
    print(f"  ✅ {len(tracks)} músicas do YouTube")
    return tracks


def match_tracks(spotify_tracks, youtube_tracks):
    print("🔗 Combinando rankings...")
    combined = []
    matched_yt = set()

    for sp in spotify_tracks:
        sp_title  = normalize(sp["title"])
        sp_artist = normalize((sp.get("artists") or [sp["artist"]])[0])
        best_match = None
        best_score = 0

        for i, yt in enumerate(youtube_tracks):
            if i in matched_yt:
                continue
            yt_title  = normalize(yt["title"])
            yt_artist = normalize((yt.get("artists") or [yt["artist"]])[0] if yt.get("artist") else "")
            title_match  = sp_title == yt_title or sp_title in yt_title or yt_title in sp_title
            artist_match = sp_artist in yt_artist or yt_artist in sp_artist
            score = (2 if title_match else 0) + (1 if artist_match else 0)
            if score >= 2 and score > best_score:
                best_score = score
                best_match = (i, yt)

        entry = {
            "artist":          sp["artist"],
            "artists":         sp.get("artists") or [sp["artist"]],
            "title":           sp["title"],
            "spotify_url":     sp["spotify_url"],
            "spotify_id":      sp["spotify_id"],
            "pos_spotify":     sp["pos_spotify"],
            "streams_spotify": sp["streams_spotify"],
            "pos_youtube":     None,
            "streams_youtube": 0,
            "in_both":         False,
        }

        if best_match:
            idx, yt = best_match
            matched_yt.add(idx)
            entry["pos_youtube"]     = yt["pos_youtube"]
            entry["streams_youtube"] = yt["streams_youtube"]
            entry["in_both"]         = True
            yt_artists = yt.get("artists") or []
            if len(yt_artists) > len(entry["artists"]):
                entry["artists"] = yt_artists
                entry["artist"]  = yt_artists[0]

        entry["total_streams"] = entry["streams_spotify"] + entry["streams_youtube"]
        combined.append(entry)

    for i, yt in enumerate(youtube_tracks):
        if i not in matched_yt:
            combined.append({
                "artist":          yt["artist"],
                "artists":         yt.get("artists") or ([yt["artist"]] if yt["artist"] else []),
                "title":           yt["title"],
                "spotify_url":     "",
                "spotify_id":      "",
                "pos_spotify":     None,
                "streams_spotify": 0,
                "pos_youtube":     yt["pos_youtube"],
                "streams_youtube": yt["streams_youtube"],
                "in_both":         False,
                "total_streams":   yt["streams_youtube"],
            })

    combined.sort(key=lambda x: x["total_streams"], reverse=True)
    for i, e in enumerate(combined):
        e["rank"] = i + 1

    in_both = sum(1 for e in combined if e["in_both"])
    print(f"  ✅ {in_both} músicas em ambas as plataformas")
    return combined


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print(f"\n🎵 Ranking Brasil Semanal — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
    os.makedirs("data", exist_ok=True)

    sb = get_supabase()
    if sb:
        print("✅ Conectado ao Supabase")
    else:
        print("⚠️  Sem Supabase — usando somente arquivos locais")

    # Carregar ranking anterior para cálculo de trend
    prev_ranking: list[dict] = []
    try:
        with open("data/ranking.json", encoding="utf-8") as f:
            prev_ranking = json.load(f).get("tracks", [])
        print(f"📂 Ranking anterior: {len(prev_ranking)} tracks")
    except FileNotFoundError:
        print("📂 Nenhum ranking anterior — primeira execução")
    prev_lookup = {_track_key(e["artist"], e["title"]): e["rank"] for e in prev_ranking}
    history = load_history(sb)

    spotify_tracks, spotify_week_date = scrape_spotify()
    time.sleep(2)
    youtube_tracks = scrape_youtube()
    # Usar a data do kworb (Spotify como referência principal)
    week_end_date = spotify_week_date
    ranking = match_tracks(spotify_tracks, youtube_tracks)

    # Calcular trend
    print("📊 Calculando variações no ranking...")
    for e in ranking:
        key       = _track_key(e["artist"], e["title"])
        prev_rank = prev_lookup.get(key)
        e["prev_rank"] = prev_rank
        if prev_rank is None:
            e["trend"] = "return" if key in history["seen_tracks"] else "new"
        elif e["rank"] < prev_rank:
            e["trend"] = f"up:{prev_rank - e['rank']}"
        elif e["rank"] > prev_rank:
            e["trend"] = f"down:{e['rank'] - prev_rank}"
        else:
            e["trend"] = "same"

    token = get_spotify_token()
    if not token:
        print("⚠️  Sem credenciais Spotify — thumbnails e gêneros serão limitados")

    # Buscar Spotify para tracks só no YouTube
    yt_only = [e for e in ranking if not e["in_both"] and e["pos_spotify"] is None]
    if token and yt_only:
        print(f"🔍 Buscando links Spotify para {len(yt_only)} músicas YouTube-only...")
        for e in yt_only:
            sid, url, thumb = search_spotify_track(e["artist"], e["title"], token)
            e["spotify_id"]  = sid
            e["spotify_url"] = url
            if thumb:
                e["thumbnail_url"] = thumb
    for e in yt_only:
        e.setdefault("thumbnail_url", "")

    # Enriquecer thumbnails via batch API
    api_artist_genres = enrich_with_spotify_api(ranking, token)

    for e in ranking:
        e.setdefault("thumbnail_url", "")

    # Resolver gêneros
    genres_config = load_genres_config(sb)
    print(f"🎨 Resolvendo gêneros ({len(genres_config['artist_genres'])} artistas manuais, "
          f"{len(genres_config['track_overrides'])} overrides)...")
    enriched_genre = 0
    for e in ranking:
        genres_list = resolve_genres(
            e,
            genres_config["artist_genres"],
            genres_config["track_overrides"],
            api_artist_genres,
        )
        e["_genres"] = genres_list
        e["genre"] = genres_list[0]
        if e["genre"] != "outros":
            enriched_genre += 1
    print(f"  ✅ {enriched_genre} tracks classificados")

    # Limpar campo interno antes de serializar
    for e in ranking:
        e.pop("_api_artist_ids", None)

    # Gerar week_label a partir da data real do kworb
    if week_end_date:
        d = datetime.strptime(week_end_date, "%Y-%m-%d")
        week_start = d - timedelta(days=6)
        week_label = f"Semana {week_start.strftime('%d/%m')} — {d.strftime('%d/%m/%Y')}"
    else:
        week_label = f"Semana de {datetime.now().strftime('%d/%m/%Y')}"

    # Persistir no Supabase
    if sb:
        try:
            _sb_upsert_artists(sb, ranking)
            _sb_save_ranking(sb, ranking, week_label, week_end_date)
        except Exception as e:
            print(f"⚠️  Falha ao salvar no Supabase: {e}")

    # Atualizar histórico
    update_history(ranking, history, sb)

    # Salvar ranking.json local (fallback para o site estático)
    output = {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "week_label":    week_label,
        "week_end_date": week_end_date,
        "tracks":        ranking,
    }
    with open("data/ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data/ranking.json gerado — {len(ranking)} músicas")
    if ranking:
        print(f"🥇 #1: {ranking[0]['artist']} — {ranking[0]['title']} ({ranking[0]['total_streams']:,} streams)")

    # Sincronizar playlists Spotify
    if SPOTIFY_REFRESH_TOKEN:
        user_token = get_spotify_user_token()
        if user_token:
            from spotify_playlists import sync_all_playlists
            sync_all_playlists(user_token, ranking)
    else:
        print("⚠️  SPOTIFY_REFRESH_TOKEN não configurado — playlists não atualizadas")


if __name__ == "__main__":
    run()
