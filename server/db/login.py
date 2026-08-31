"""
Companheiro do fluxo admin break-glass (usado antes de register.py).

Usuários finais NÃO usam este script — usam client/connect.py, que faz o login
e sobe o token cifrado para o servidor sem expor a chave Fernet localmente.

Abre o Chromium via Playwright, navega para o NotebookLM e aguarda o login manual.
Detecta automaticamente quando o login foi concluido e salva o storage_state.json.

Uso:
    python login.py --email admin@exemplo.com
"""

import argparse
import json
import pathlib

from playwright.sync_api import sync_playwright

PROFILES_DIR = pathlib.Path.home() / ".notebooklm" / "profiles"
NOTEBOOKLM_URL = "https://notebook.google.com"


def login(email: str) -> pathlib.Path:
    profile_dir = PROFILES_DIR / email.replace("@", "_at_")
    profile_dir.mkdir(parents=True, exist_ok=True)
    out = profile_dir / "storage_state.json"

    print(f"[login] Abrindo Chromium para: {email}")
    print("[login] Faca o login com a conta Google correta.")
    print("[login] O token sera capturado automaticamente apos o login.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context()
        page = context.new_page()
        page.goto(NOTEBOOKLM_URL)

        # Aguarda ate o usuario estar de volta no NotebookLM (pos-login Google)
        print("[login] Aguardando login...")
        page.wait_for_url(
            lambda url: "notebook.google.com" in url and "accounts.google.com" not in url,
            timeout=180000,  # 3 minutos para o usuario logar
        )

        # Aguarda carregar a pagina principal
        page.wait_for_load_state("networkidle", timeout=15000)

        storage = context.storage_state()
        out.write_text(json.dumps(storage, indent=2))
        out.chmod(0o600)
        browser.close()

    print(f"[login] Token salvo em: {out}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Email Google usado no NotebookLM")
    args = parser.parse_args()
    login(args.email)
