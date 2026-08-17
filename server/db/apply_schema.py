"""
Aplica o schema.sql no Postgres. Le a conexao de DATABASE_URL (env).

Uso:
    set DATABASE_URL=postgres://user:pass@host:5432/db
    python apply_schema.py
"""
import os
import pathlib
import sys
from urllib.parse import urlparse

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERRO: defina a variavel de ambiente DATABASE_URL")
    sys.exit(1)


def _db_params() -> dict:
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


schema_file = pathlib.Path(__file__).parent / "schema.sql"
schema = schema_file.read_text(encoding="utf-8")

try:
    conn = psycopg.connect(**_db_params())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(schema)
    print("Schema aplicado com sucesso.")

    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'notebooklm'
        ORDER BY table_name
    """)
    print("Tabelas criadas:")
    for t in cur.fetchall():
        print(" -", t[0])
    conn.close()
except Exception as e:
    print("ERRO:", e)
    sys.exit(1)
