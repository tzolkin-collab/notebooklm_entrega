"""
Gera (ou regenera) o token de conector de um usuario e salva no Postgres.
O usuario usa esse token ao adicionar o conector MCP no Claude.

Uso:
    set DATABASE_URL=postgres://...
    python gen_token.py --email admin@exemplo.com
"""
import argparse
import hashlib
import os
import secrets
import sys
from urllib.parse import urlparse

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERRO: defina DATABASE_URL")
    sys.exit(1)


def _params() -> dict:
    u = urlparse(DATABASE_URL)
    p = {"host": u.hostname, "port": u.port or 5432, "dbname": u.path.lstrip("/"),
         "user": u.username, "password": u.password}
    query = u.query or ""
    if "sslmode=disable" in query:
        p["sslmode"] = "disable"
    elif "sslmode=" not in query:
        p["sslmode"] = "require"  # fail-secure: TLS por padrao
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    args = ap.parse_args()

    token = "nlm_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()  # banco guarda só o hash

    conn = psycopg.connect(**_params())
    conn.autocommit = True
    cur = conn.execute(
        "UPDATE notebooklm.users SET api_token = %s WHERE email = %s RETURNING email, nivel",
        (token_hash, args.email),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        print(f"ERRO: usuario {args.email} nao encontrado. Registre-o primeiro.")
        sys.exit(1)

    print(f"\nToken gerado para {row[0]} (nivel {row[1]}):\n")
    print(f"  {token}\n")
    print("Use esse token ao adicionar o conector no Claude.")


if __name__ == "__main__":
    main()
