# 🎵 Ranking Brasil Semanal — Spotify + YouTube

Ranking combinado das músicas mais tocadas no Brasil, cruzando os dados semanais do Spotify e do YouTube. Atualizado automaticamente toda **sexta-feira**.

## Como funciona

1. O GitHub Actions roda o `scraper.py` toda sexta às 10h (horário de Brasília)
2. O scraper coleta os dados de:
   - **Spotify BR Weekly**: `kworb.net/spotify/country/br_weekly.html`
   - **YouTube BR Weekly**: `kworb.net/youtube/insights/br.html`
3. As músicas presentes em ambas as plataformas têm seus streams somados
4. O ranking é gerado em `data/ranking.json` e publicado via GitHub Pages

## Metodologia de pontuação

- **Músicas em ambas as plataformas**: streams Spotify + streams YouTube
- **Músicas só no Spotify**: streams Spotify
- **Músicas só no YouTube**: streams YouTube
- O link do Spotify é gerado automaticamente a partir do ID extraído do kworb.net

## Estrutura do projeto

```
ranking-brasil/
├── index.html              # Página do ranking (GitHub Pages)
├── scraper.py              # Script de scraping
├── requirements.txt        # Dependências Python
├── data/
│   └── ranking.json        # Dados gerados automaticamente
└── .github/
    └── workflows/
        └── weekly-ranking.yml   # Automação semanal
```

## Como configurar

### 1. Faça o fork ou upload deste repositório no GitHub

### 2. Configure as credenciais do Spotify

O scraper usa a [Spotify Web API](https://developer.spotify.com/dashboard) para buscar thumbnails, gêneros e links de músicas do YouTube. Para isso você precisa de um app no Spotify:

1. Acesse [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) e crie um novo app
2. Copie o **Client ID** e o **Client Secret** do app
3. No repositório, vá em **Settings → Secrets and variables → Actions**
4. Adicione dois secrets:
   - `SPOTIFY_CLIENT_ID` — o Client ID do seu app
   - `SPOTIFY_CLIENT_SECRET` — o Client Secret do seu app

> Sem essas credenciais o scraper ainda funciona, mas sem thumbnails, gêneros e sem links Spotify para músicas exclusivas do YouTube.

### 3. Ative o GitHub Pages
- Vá em **Settings → Pages**
- Em **Source**, selecione `gh-pages` como branch
- Salve

### 4. Ative o GitHub Actions
- Vá em **Actions** e habilite os workflows

### 5. Execute manualmente pela primeira vez
- Em **Actions → Atualizar Ranking Semanal → Run workflow**

Depois disso, toda sexta-feira o ranking será atualizado automaticamente!

## Acesso

Após configurar, o ranking estará disponível em:
`https://SEU-USUARIO.github.io/ranking-brasil/`
