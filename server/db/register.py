"""
FERRAMENTA ADMIN — break-glass (servidor / máquina confiável do admin).

⚠️  Requer a NOTEBOOKLM_ENCRYPTION_KEY (chave Fernet) e DATABASE_URL diretos.
    NUNCA rode em máquina de usuário final: quem tem a chave Fernet decifra o
    token de TODA a equipe. O caminho normal de onboarding é client/connect.py
    (login local + upload via HTTPS; o servidor cifra e cria cadastro pendente).
    Use este script só para registro direto pelo admin, em ambiente confiável.

Criptografa o storage_state.json de um email e registra no Postgres.
Deve rodar APÓS login.py (na mesma máquina).

Uso:
    python register.py --email admin@exemplo.com --nivel admin
"""

import argparse
import os
import pathlib
import sys
from urllib.parse import urlparse

from cryptography.fernet import Fernet
import psycopg
from dotenv import load_dotenv

load_dotenv()

PROFILES_DIR = pathlib.Path.home() / ".notebooklm" / "profiles"
ENCRYPTION_KEY = os.environ["NOTEBOOKLM_ENCRYPTION_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]


def _parse_db_params() -> dict:
    """Parse tolerante a caracteres especiais nao-encoded na senha (mesma
    logica de server/db.py): a DATABASE_URL do EasyPanel traz a senha
    literal, nao percent-encoded, entao NAO fazemos unquote() aqui — fazer
    isso corrompe senhas com '%' literal."""
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
    else:
        params["sslmode"] = "require"  # fail-secure: TLS por padrao
    return {k: v for k, v in params.items() if v is not None}


def register(email: str, nome: str, nivel: str, profile: str | None = None) -> None:
    # Resolve o caminho do storage_state: profile nomeado ou pasta baseada no email
    if profile:
        state_file = PROFILES_DIR / profile / "storage_state.json"
    else:
        state_file = PROFILES_DIR / email.replace("@", "_at_") / "storage_state.json"
        # Fallback: tenta o profile 'default' se nao encontrar pelo email
        if not state_file.exists():
            state_file = PROFILES_DIR / "default" / "storage_state.json"

    if not state_file.exists():
        print(f"[register] ERRO: {state_file} nao encontrado. Execute 'notebooklm login' primeiro.")
        sys.exit(1)

    print(f"[register] Usando token de: {state_file}")

    raw = state_file.read_text()
    fernet = Fernet(ENCRYPTION_KEY.encode())
    encrypted = fernet.encrypt(raw.encode()).decode()

    conn = psycopg.connect(**_parse_db_params())
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notebooklm.users (email, nome, nivel, ativo)
                    VALUES (%s, %s, %s, true)
                    ON CONFLICT (email) DO UPDATE SET nome = EXCLUDED.nome, nivel = EXCLUDED.nivel;
                    """,
                    (email, nome, nivel),
                )
                cur.execute(
                    """
                    INSERT INTO notebooklm.tokens (email, storage_state, atualizado_em)
                    VALUES (%s, %s, now())
                    ON CONFLICT (email) DO UPDATE SET storage_state = EXCLUDED.storage_state, atualizado_em = now();
                    """,
                    (email, encrypted),
                )
        print(f"[register] Token de {email} registrado com sucesso no Postgres.")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--nome", default="")
    parser.add_argument("--nivel", default="juridico",
                        choices=["admin", "gestor", "juridico", "financeiro"])
    parser.add_argument("--profile", default=None,
                        help="Nome do profile notebooklm (ex: default)")
    args = parser.parse_args()
    register(args.email, args.nome, args.nivel, args.profile)
