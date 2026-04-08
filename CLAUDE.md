# CLAUDE.md — RankingBR

## Projeto

RankingBR: ranking musical semanal do Brasil combinando Spotify + YouTube.
Stack: Python (scraper/sync), HTML/JS (frontend), Supabase (banco), GitHub Actions (CI), GitHub Pages (deploy).

## Supabase

- **Project ID:** `suzcbyzidnzzahwrkveh`
- **Region:** sa-east-1
- **Serviços de log disponíveis:** api, postgres, edge-function, auth, storage, realtime

## Scripts principais

- `scraper.py` — coleta ranking semanal do kworb.net
- `sync_discography.py` — sync discografia de artistas via Spotify API (blocos de 100, pausa 10min)
- `spotify_playlists.py` — sync playlists Spotify por gênero
- `config.js` — config Supabase compartilhada no frontend

## Regra obrigatória: auto-teste com logs após cada feature

Sempre que implementar ou modificar uma feature que interaja com o Supabase (insert, update, delete, chamadas API), você DEVE:

1. **Rodar o script/feature** modificado
2. **Consultar os logs do Supabase** usando `mcp__claude_ai_Supabase__get_logs` com:
   - `project_id`: `suzcbyzidnzzahwrkveh`
   - `service`: o serviço relevante (geralmente `api` ou `postgres`)
3. **Verificar nos logs** se:
   - As operações completaram sem erros (status 2xx)
   - Não houve erros 4xx/5xx inesperados
   - O volume de operações está coerente com o esperado
4. **Reportar o resultado** ao usuário com um resumo dos logs (quantas operações, erros encontrados, etc.)

Se a feature não interage com Supabase (ex: mudança apenas no frontend estático), verificar via browser ou lógica do código.

## Convenções

- Commits em português, prefixos: `feat:`, `fix:`, `docs:`, `refactor:`
- Não criar arquivos .md desnecessários
- Preferir editar arquivos existentes a criar novos
- Scripts Python usam variáveis de ambiente para credenciais (nunca hardcoded)
