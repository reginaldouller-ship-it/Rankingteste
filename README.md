# RankingBR — Ranking Musical Semanal do Brasil

Ranking combinado das musicas mais tocadas no Brasil, cruzando dados semanais do **Spotify** e **YouTube**. Atualizado automaticamente todo **sabado** via GitHub Actions, com persistencia no **Supabase** e frontend publicado via **GitHub Pages**.

## Funcionalidades

- **Ranking semanal** — Top 200 Spotify + Top 100 YouTube combinados por streams
- **Calendario de semanas** — Navegue entre semanas com calendario visual estilo Spotify
- **Gestao de generos** — Classifique artistas por genero (multi-genero suportado)
- **Discografia por artista** — Sync completo da discografia via Spotify API com ranking de popularidade
- **Playlists automaticas** — Playlists Spotify por genero + "Mais Tocadas", sincronizadas semanalmente
- **Historico de tracks** — Tracking de aparicoes, tendencias (new/up/down/return)
- **Rate limit inteligente** — Retry com Retry-After, batch de albuns, timer persistente no frontend

## Como funciona

1. **Scraping** — `scraper.py` coleta dados do [kworb.net](https://kworb.net) (Spotify BR Weekly + YouTube BR)
2. **Matching** — Cruza musicas entre plataformas por titulo/artista e soma streams
3. **Enriquecimento** — Busca thumbnails, generos e links via Spotify Web API (batch)
4. **Persistencia** — Salva ranking no Supabase + arquivo local `data/ranking.json`
5. **Discografia** — `sync_discography.py` atualiza discografia completa dos artistas sincronizados
6. **Playlists** — `spotify_playlists.py` sincroniza playlists Spotify por genero
7. **Deploy** — GitHub Pages publica o frontend automaticamente

## Estrutura do projeto

```
Rankingteste-main/
  index.html              — Pagina principal (ranking + calendario)
  genres.html             — Gestao de generos e discografia de artistas
  genres-app.js           — JS da pagina de generos
  config.js               — Config Supabase compartilhada (URL, anon key, helpers)
  styles.css              — CSS compartilhado (variaveis, reset, componentes)
  scraper.py              — Scraper semanal Spotify + YouTube (kworb.net)
  sync_discography.py     — Sync semanal de discografia de todos os artistas
  spotify_playlists.py    — Sync de playlists Spotify por genero
  spotify_auth.py         — OAuth flow para obter refresh_token
  sync_playlists_runner.py — Runner standalone de sync de playlists
  requirements.txt        — Dependencias Python
  data/
    ranking.json          — Ranking local (fallback)
    ranking_history.json  — Historico de tracks
    genres.json           — Config de generos (fallback local)
    playlist_ids.json     — Cache genero -> playlist_id do Spotify
  .github/workflows/
    weekly-ranking.yml    — Scraper + sync discografia (sabado 13h UTC)
    sync-playlists.yml    — Sync playlists on-demand (workflow_dispatch)
    jekyll-gh-pages.yml   — Deploy GitHub Pages
```

## Configuracao

### 1. Fork do repositorio

Fork ou clone este repositorio no GitHub.

### 2. Criar app no Spotify

1. Acesse [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) e crie um novo app
2. Em **Redirect URIs**, adicione: `https://SEU-USUARIO.github.io/SEU-REPO/callback`
3. Copie o **Client ID** e o **Client Secret**

### 3. Criar projeto no Supabase

1. Crie um projeto em [supabase.com](https://supabase.com) (regiao `sa-east-1` recomendada)
2. Crie as tabelas necessarias (ver secao Banco de Dados abaixo)
3. Copie a **URL** e a **Service Role Key** do projeto

### 4. Configurar GitHub Secrets

No repositorio, va em **Settings > Secrets and variables > Actions** e adicione:

| Secret | Descricao |
|--------|-----------|
| `SPOTIFY_CLIENT_ID` | Client ID do app Spotify |
| `SPOTIFY_CLIENT_SECRET` | Client Secret do app Spotify |
| `SPOTIFY_REFRESH_TOKEN` | Token OAuth do usuario (gerado pelo `spotify_auth.py`) |
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Service Role Key do Supabase |

### 5. Gerar Refresh Token do Spotify

```bash
export SPOTIFY_CLIENT_ID="seu_client_id"
export SPOTIFY_CLIENT_SECRET="seu_client_secret"
python spotify_auth.py
```

O script abre o navegador para autorizacao OAuth. Apos autorizar, cole a URL de callback no terminal. O refresh token exibido deve ser salvo como GitHub Secret `SPOTIFY_REFRESH_TOKEN`.

**Escopos utilizados:** `playlist-modify-public`, `playlist-modify-private`, `playlist-read-private`, `playlist-read-collaborative`

### 6. Ativar GitHub Pages

- Va em **Settings > Pages**
- Em **Source**, selecione `gh-pages` como branch
- Salve

### 7. Primeira execucao

- Va em **Actions > Atualizar Ranking Semanal > Run workflow**

Apos isso, o ranking sera atualizado automaticamente todo sabado as 10h (Brasilia).

## Banco de Dados (Supabase)

| Tabela | Descricao |
|--------|-----------|
| `ranking_weeks` | Semanas do ranking (id, week_label, week_end_date, generated_at) |
| `ranking_tracks` | Tracks por semana (week_id FK, rank, artist, artists, title, streams...) |
| `artists` | Artistas unicos (name, track_count, spotify_id, discography_synced_at) |
| `artist_genres` | Relacao N:N artista-genero |
| `genres` | Lista de generos |
| `artist_tracks` | Discografia por artista (track_name, popularity, is_featured, track_artists...) |
| `track_overrides` | Override manual de genero por track (spotify_id, genre_id) |
| `track_history` | Historico de aparicoes de tracks |

**Views:** `latest_ranking`, `artists_with_genres`, `track_overrides_with_genres`

### Supabase Edge Functions

| Funcao | Descricao |
|--------|-----------|
| `sync-artist-discography` | Sync discografia de artista via Spotify API com batch de albuns e rate limit handling |
| `trigger-playlist-sync` | Proxy seguro para disparar workflow sync-playlists.yml via GitHub API |

## Spotify API — Rate Limiting

O projeto implementa varias estrategias para evitar rate limits:

- **Batch de albuns** — `GET /v1/albums?ids=` busca ate 20 albuns por request (em vez de 1 por 1)
- **Batch de tracks** — `GET /v1/tracks?ids=` busca ate 50 tracks por request
- **Retry com Retry-After** — Respeita o header `Retry-After` do Spotify, aguarda e tenta novamente (ate 5 retries, max 120s de espera)
- **Delays adaptativos** — 1s entre artistas, 5s apos rate limit, 0.1-0.15s entre batches
- **Timer persistente** — Frontend salva timestamp de expiracao no localStorage, exibe tempo restante formatado (h/min/s) ao reabrir a pagina

## Dependencias

```
Python 3.11+
requests >= 2.31
beautifulsoup4 >= 4.12
supabase >= 2.0
```

## Acesso

Apos configurar, o ranking estara disponivel em:
```
https://SEU-USUARIO.github.io/SEU-REPO/
```

A pagina de gestao de generos e discografia:
```
https://SEU-USUARIO.github.io/SEU-REPO/genres.html
```
