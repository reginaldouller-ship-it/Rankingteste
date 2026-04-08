# RankingBR — Progresso do Projeto

## Feito

### Code Review + Refatoramento (07/04/2026)
- [x] Corrigido XSS no index.html — `esc()` em todos os dados dinâmicos
- [x] Corrigido chave `}` faltante em `refreshGenreFilters` (era codigo morto, removido)
- [x] Extraido config Supabase para `config.js` compartilhado (URL, anon key, sbGet, sbPost, sbRpc, esc)
- [x] Extraido CSS compartilhado para `styles.css` (variaveis, reset, logo, botoes)
- [x] Extraido JS do `genres.html` para `genres-app.js`
- [x] Adicionado `console.warn` nos `catch` silenciosos (antes engoliam erros)
- [x] Trocado `datetime.utcnow()` por `datetime.now(timezone.utc)` no scraper.py (3 ocorrencias)
- [x] Fixado versoes no requirements.txt (`requests>=2.31,<3`, `beautifulsoup4>=4.12,<5`, `supabase>=2.0,<3`)
- [x] Adicionado `rel="noopener"` nos links do footer
- [x] PR #7 criado, conflitos resolvidos e mergeado na main

### Limpeza de Dados (07/04/2026)
- [x] Removidos 10 rankings duplicados do Supabase (eram testes, todos identicos)
- [x] Mantido apenas ranking #11 como unico registro

### Seletor de Semana — Dropdown (07/04/2026)
- [x] Substituido badge estatico `week-badge` por `<select>` dropdown
- [x] `loadRanking()` refatorado para carregar por `week_id`
- [x] PR mergeado na main

### Calendario Estilo Spotify (07/04/2026)
- [x] Substituido dropdown `<select>` por botao com popup de calendario
- [x] Calendario exibe 2 meses lado a lado com navegacao por setas
- [x] Semana selecionada destacada em roxo (dias in-week + dia end selected)
- [x] Dias com dados clicaveis, dias futuros esmaecidos
- [x] Responsivo para mobile (1 coluna)
- [x] Corrigido bug de espacamento no grid do calendario (grid-auto-rows: 32px)

### Scraper — Extracao de Week Ending (07/04/2026)
- [x] Nova funcao `extract_week_date()` extrai data "Week ending YYYY/MM/DD" do kworb
- [x] Spotify retorna no titulo: "Spotify Weekly Chart - Brazil - 2026/04/02"
- [x] YouTube retorna: "YouTube Brazil - Week ending 2026/04/02"
- [x] `scrape_spotify()` agora retorna tupla `(tracks, week_date)`
- [x] `week_label` gerado automaticamente no formato "Semana DD/MM — DD/MM/YYYY"
- [x] `week_end_date` salvo no Supabase e no ranking.json

### Banco de Dados (07/04/2026)
- [x] Adicionada coluna `week_end_date` (date) na tabela `ranking_weeks`
- [x] Corrigido registro existente (#11): era semana 20/03—26/03/2026, nao 03/04
- [x] Criada semana #12: Semana 27/03—02/04/2026
- [x] Inseridos 246 tracks da semana #12 (10 batches de 25, duplicatas limpas)
- [x] Inseridos 20 artistas novos da semana #12 (Mc Jacare, KATSEYE, Michel Telo, etc.)
- [x] Corrigido bug de split de duplas no regex `_FEAT_RE` — `&` nao e mais separador
  - Antes: "Henrique & Juliano" -> ["Henrique", "Juliano"] (ERRADO)
  - Depois: "Henrique & Juliano" -> ["Henrique & Juliano"] (CORRETO)
- [x] Removidos artistas splitados incorretamente do Supabase (Henrique, Juliano, Felipe, Rodrigo, etc.)
- [x] Corrigido duplicatas por case-sensitivity (MC IG vs Mc IG) e unicode (NFD vs NFC no acento de Jacaré)
- [x] Adicionado `normalize_artist_name()` no scraper — aplica Unicode NFC + strip em todos os nomes de artistas
- [x] Aplicado em `scrape_spotify()` e `scrape_youtube()` para prevenir duplicatas futuras

### Sincronização de Playlists Spotify (07/04/2026)
- [x] Criado `spotify_playlists.py` — sync de playlists por gênero + "Mais Tocadas"
- [x] Criado `spotify_auth.py` — fluxo OAuth para obter refresh_token
- [x] Criado `sync_playlists_runner.py` — script standalone que lê ranking+gêneros do Supabase e sincroniza playlists
- [x] Criado workflow `.github/workflows/sync-playlists.yml` (workflow_dispatch only)
- [x] Deploy da Edge Function `trigger-playlist-sync` no Supabase — proxy seguro para disparar o workflow
- [x] Botão "Sync Playlists" no header do `index.html` com feedback visual (syncing/success/error)
- [ ] Configurar secret `GITHUB_PAT` no Supabase (fine-grained PAT com scope `actions:write`)
- [ ] Testar fluxo completo: alterar gênero → clicar Sync → verificar playlists atualizadas

### Skill de Code Review
- [x] Criada skill `code-review` em `~/.claude/skills/code-review/SKILL.md`
- [x] Revisao por severidade: Critico, Alto, Medio, Baixo
- [x] Checklist OWASP Top 10 + checklist de performance
- [x] Formato de relatorio estruturado com codigo atual + correcao sugerida

### GitHub CLI
- [x] Instalado `gh` CLI via winget (v2.89.0)
- [x] Autenticado pelo usuario

---

## A Fazer

### Dados
- [ ] Rodar scraper via GitHub Actions e verificar que `week_end_date` e salvo corretamente
- [ ] Enriquecer semana #12 com thumbnails e generos (rodar scraper completo com Supabase SDK)

### Calendario
- [ ] Testar navegacao entre semanas no calendario (precisa de 2+ semanas com dados)
- [ ] Verificar highlight da semana 20/03—26/03 no calendario ao seleciona-la

### Scraper
- [ ] Instalar Visual C++ Build Tools para compilar `pyiceberg` (dependencia do supabase SDK)
  - Alternativa: usar `pip install supabase --no-deps` ou versao mais leve
- [ ] Testar scraper completo localmente com persistencia no Supabase

### Deploy
- [x] Commit direto na main: calendario, scraper, PROGRESS.md (42ee77b)
- [x] Cron do scraper trocado de sexta (5) para sabado (6) — 13h UTC
- [ ] Verificar que GitHub Actions roda o scraper na proxima sexta-feira
- [ ] Confirmar que o deploy no GitHub Pages funciona com os novos arquivos (config.js, styles.css, genres-app.js)

### Multi-Gênero + Playlist Links (07/04/2026)
- [x] Migração DB: PK `track_overrides` alterada de `(spotify_id)` para `(spotify_id, genre_id)`
- [x] Nova RPC `toggle_track_override` — adiciona/remove gênero sem substituir os existentes
- [x] View `track_overrides_with_genres` agora retorna `genre_names` (array)
- [x] Dropdown de override com checkboxes multi-seleção (toggle individual)
- [x] `getEffectiveGenres()` retorna array de gêneros (override ou artista)
- [x] `enrichTrackGenres()` coleta gêneros de TODOS os artistas (union)
- [x] Tracks com artista multi-gênero aparecem em todos os filtros correspondentes
- [x] Backend `sync_all_playlists` coloca track em múltiplas playlists de gênero
- [x] Seção "Playlists no Spotify" na home com links diretos para cada playlist
- [x] Playlist "Mais Tocadas" usa multi-gênero para inclusão

### Playlists Spotify
- [x] Criar GitHub PAT (fine-grained) com permissão `actions:write` no repo Rankingteste
- [x] Salvar PAT como secret `GITHUB_PAT` no Supabase (Dashboard → Edge Functions → Secrets)
- [ ] Testar botão "Sync Playlists" no site publicado
- [ ] Testar alteração de gênero multi-seleção + sync + verificar playlist no Spotify

### Code Review + Otimizações Spotify API (08/04/2026)
- [x] **FIX: Crashes NoneType** — `sync_discography.py` e `scraper.py` agora verificam retorno `None` de `spotify_get`/`_spotify_get` antes de usar `.json()` ou `.get()`
- [x] **FIX: Concorrência Edge Function** — `rateLimitCount` e `lastRetryAfter` movidos de variáveis globais para `RequestState` por request, evitando estado compartilhado entre requests concorrentes
- [x] **FIX: Escopo OAuth** — Adicionado `playlist-modify-private` ao `SCOPES` em `spotify_auth.py` para suportar playlists privadas. Refresh token re-gerado.
- [x] **OTIMIZAÇÃO: Batch de álbuns** — `sync_discography.py` e Edge Function agora usam `GET /v1/albums?ids=` (até 20 álbuns por request) em vez de buscar tracks álbum por álbum. Reduz ~80% das chamadas API para artistas com muitos álbuns.
- [x] **OTIMIZAÇÃO: ALBUMS_PER_PAGE** — Edge Function aumentado de 15 para 50, reduzindo paginação desnecessária.
- [x] **OTIMIZAÇÃO: Resiliência rate limit** — `spotify_get` no sync semanal aumentado para 5 retries, aceita Retry-After até 120s. Delay adaptativo entre artistas (5s após rate limit, 1s normal).
- [x] **FEAT: Retry-After no frontend** — Quando a API retorna 429, exibe tempo de espera formatado (h/min/s) na tela de sync do artista.
- [x] **FEAT: Timer persistente** — Rate limit salvo no `localStorage` com timestamp de expiração. Ao reabrir a página/painel, mostra tempo restante no botão sem sobrescrever a discografia já carregada.
- [x] Edge Function `sync-artist-discography` atualizada para v23

### Discografia de Artistas (07/04/2026)
- [x] **BUG corrigido**: Discografia puxava músicas de álbuns `appears_on` onde o artista não era performer — filtro adicionado na Edge Function `sync-artist-discography` (v4): só inclui tracks onde `artistId` está no array `artists` da faixa.
- [x] **BUG corrigido**: Timeout de 150s (status 546) — Edge Function v8 busca tracks de álbuns em paralelo (5 concurrent com Promise.allSettled) em vez de sequencial.
- [x] Badge **FEAT** exibido nas músicas onde o artista é participante, não o artista principal.
- [x] Lista de todos os artistas da faixa exibida abaixo do nome da música na discografia.
- [x] Colunas `track_artists` (text[]) e `is_featured` (boolean) adicionadas à tabela `artist_tracks`.
- [ ] Testar fluxo completo: sincronizar artista → verificar badge FEAT e participantes corretos.

### Melhorias Futuras
- [ ] Verificar RLS no Supabase para todas as tabelas acessiveis via anon key
- [ ] Otimizar thumbnail loading com batching (Promise.allSettled em grupos de 5)
- [ ] Considerar extrair JS inline do index.html para app.js (como feito com genres-app.js)
- [ ] Adicionar indicador visual de "carregando" ao trocar semana no calendario

---

## Estrutura de Arquivos

```
Rankingteste-main/
  index.html          — Pagina principal (ranking + calendario)
  genres.html          — Gestao de generos (HTML + CSS)
  genres-app.js        — JS extraido do genres.html
  config.js            — Config Supabase compartilhada (URL, keys, helpers)
  styles.css           — CSS compartilhado (variaveis, reset, logo)
  scraper.py           — Scraper Spotify + YouTube (kworb.net)
  sync_discography.py  — Sync semanal de discografia de todos os artistas
  spotify_playlists.py — Sync de playlists Spotify por genero
  spotify_auth.py      — OAuth flow para obter refresh_token
  sync_playlists_runner.py — Runner standalone de sync (le ranking do Supabase)
  requirements.txt     — Dependencias Python (versoes fixadas)
  data/
    ranking.json       — Ranking local (fallback)
    ranking_history.json — Historico de tracks
    genres.json        — Config de generos (fallback local)
    playlist_ids.json  — Cache genero → playlist_id do Spotify
  .github/workflows/
    weekly-ranking.yml — Scraper automatico (sabado 13h UTC)
    sync-playlists.yml — Sync playlists on-demand (workflow_dispatch)
    jekyll-gh-pages.yml — Deploy GitHub Pages
```

## Banco de Dados (Supabase)

| Tabela | Descricao |
|--------|-----------|
| ranking_weeks | Semanas do ranking (id, week_label, week_end_date, generated_at) |
| ranking_tracks | Tracks por semana (week_id FK, rank, artist, artists, title, streams...) |
| artists | Artistas unicos com track_count |
| artist_genres | Relacao N:N artista-genero |
| genres | Lista de generos |
| track_overrides | Override manual de genero por track (spotify_id) |
| track_history | Historico de aparicoes de tracks |
| Views: latest_ranking, artists_with_genres, track_overrides_with_genres |

### Supabase Edge Functions

| Funcao | Versao | Descricao |
|--------|--------|-----------|
| trigger-playlist-sync | v4 | Proxy seguro para disparar workflow sync-playlists.yml via GitHub API |
| sync-artist-discography | v23 | Sync discografia de artista com batch de álbuns, rate limit handling e retry_after no response |
