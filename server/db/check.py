"""
FERRAMENTA ADMIN — break-glass (servidor / máquina confiável do admin).

⚠️  Requer a NOTEBOOKLM_ENCRYPTION_KEY (chave Fernet) e DATABASE_URL diretos —
    descriptografa os tokens da equipe para testá-los. NUNCA rode em máquina de
    usuário final. Para checar token sem a chave, use o endpoint /api/auth/check
    (Bearer do usuário) ou a tool MCP `verificar_token`.

Verifica a saúde dos tokens de todos os usuários ativos no Postgres.
Testa se o cookie ainda autentica no NotebookLM.

Uso:
    python check.py
    python check.py --email admin@exemplo.com
"""

import argparse
import json
import os
import sys
import tempfile
import pathlib
from urllib.parse import urlparse

from cryptography.fernet import Fernet
import psycopg
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

ENCRYPTION_KEY = os.environ["NOTEBOOKLM_ENCRYPTION_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]


def _db_params() -> dict:
    """Parse tolerante a caracteres especiais nao-encoded na senha (mesma
    logica de server/db.py) — evita 'invalid percent-encoded token' do
    psycopg ao passar a URL crua direto para connect()."""
    u = urlparse(DATABASE_URL)
    params = {
        "host": u.hostname,
        "port": u.port or 5432,
        "dbname": u.path.lstrip("/"),
        "user": u.username,
        "password": u.password,
    }
    query = u.query or ""
    if "sslmode=disable" in query:
        params["sslmode"] = "disable"
    elif "sslmode=" not in query:
        params["sslmode"] = "require"  # fail-secure: TLS por padrao
    return {k: v for k, v in params.items() if v is not None}


def decrypt_state(encrypted: str) -> dict:
    fernet = Fernet(ENCRYPTION_KEY.encode())
    return json.loads(fernet.decrypt(encrypted.encode()).decode())


def test_token(storage_state: dict) -> bool:
    """Retorna True se o cookie autentica no NotebookLM."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()
        try:
            response = page.goto("https://notebook.google.com", wait_until="networkidle", timeout=20000)
            # Se redirecionar para accounts.google.com, o token expirou
            is_valid = "accounts.google.com" not in page.url
            return is_valid
        except Exception:
            return False
        finally:
            browser.close()


def check_all(email_filter: str | None = None) -> None:
    conn = psycopg.connect(**_db_params())
    try:
        with conn.cursor() as cur:
            if email_filter:
                cur.execute(
                    "SELECT u.email, u.nome, t.storage_state FROM notebooklm.users u "
                    "JOIN notebooklm.tokens t ON u.email = t.email "
                    "WHERE u.ativo = true AND u.email = %s",
                    (email_filter,),
                )
            else:
                cur.execute(
                    "SELECT u.email, u.nome, t.storage_state FROM notebooklm.users u "
                    "JOIN notebooklm.tokens t ON u.email = t.email WHERE u.ativo = true"
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[check] Nenhum usuário com token encontrado.")
        return

    print(f"\n{'Email':<40} {'Nome':<25} {'Status'}")
    print("-" * 80)
    for email, nome, encrypted in rows:
        try:
            state = decrypt_state(encrypted)
            valid = test_token(state)
            status = "✅ válido" if valid else "❌ EXPIRADO — rode login.py + register.py"
        except Exception as e:
            status = f"⚠️  erro: {e}"
        print(f"{email:<40} {(nome or ''):<25} {status}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=None, help="Checar apenas este email")
    args = parser.parse_args()
    check_all(args.email)
