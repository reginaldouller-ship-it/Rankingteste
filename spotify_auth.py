#!/usr/bin/env python3
"""
Autenticação OAuth do Spotify — executar uma única vez para obter o refresh token.

Uso:
    1. Defina SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET como variáveis de ambiente
    2. No Spotify Developer Dashboard, adicione a Redirect URI:
       https://rankingbr.github.io/callback
    3. Execute: py spotify_auth.py
    4. Autorize no navegador
    5. Copie a URL da página de redirecionamento e cole no terminal
    6. Salve o refresh_token exibido como GitHub Secret (SPOTIFY_REFRESH_TOKEN)
"""

import os
import sys
import webbrowser
import urllib.parse
import requests

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = "https://reginaldouller-ship-it.github.io/Rankingteste/callback"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private playlist-read-collaborative"


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("❌ Defina SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET como variáveis de ambiente")
        sys.exit(1)

    # Montar URL de autorização
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    })

    print("🔑 Abrindo navegador para autorização Spotify...")
    print(f"   URL: {auth_url}\n")
    webbrowser.open(auth_url)

    print("Após autorizar, o navegador vai redirecionar para uma página (pode dar erro 404, é normal).")
    print("Copie a URL COMPLETA da barra de endereço e cole aqui.\n")
    redirect_url = input("Cole a URL aqui: ").strip()

    if not redirect_url:
        print("❌ Nenhuma URL fornecida")
        sys.exit(1)

    # Extrair code da URL
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)

    if "error" in params:
        print(f"❌ Erro na autorização: {params['error'][0]}")
        sys.exit(1)

    auth_code = params.get("code", [None])[0]
    if not auth_code:
        print("❌ Código de autorização não encontrado na URL")
        print(f"   URL recebida: {redirect_url}")
        sys.exit(1)

    print("✅ Código recebido, trocando por tokens...")

    # Trocar code por tokens
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print(f"❌ Resposta inesperada: {data}")
        sys.exit(1)

    # Obter user_id para confirmar
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = requests.get("https://api.spotify.com/v1/me", headers=headers, timeout=10).json()

    print(f"\n{'='*60}")
    print(f"✅ Autenticado como: {me.get('display_name', '?')} ({me.get('id', '?')})")
    print(f"{'='*60}")
    print(f"\n🔐 REFRESH TOKEN (salve como GitHub Secret 'SPOTIFY_REFRESH_TOKEN'):\n")
    print(refresh_token)
    print(f"\n{'='*60}")
    print("⚠️  Este token não expira, mas pode ser revogado manualmente no Spotify.")


if __name__ == "__main__":
    main()
