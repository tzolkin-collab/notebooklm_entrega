"""Valida as duas envs sem exibir segredos; --apply aplica so bot_links.sql."""
import argparse
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

from dotenv import dotenv_values
import psycopg

ROOT = Path(__file__).resolve().parents[1]


def read_settings(server_path, bot_path):
    server = dotenv_values(server_path, interpolate=False)
    bot = dotenv_values(bot_path, interpolate=False)
    for label, settings, required in (
        ("servidor", server, ("DATABASE_URL", "PUBLIC_URL", "NOTEBOOKLM_BOT_CALLBACK_KEY")),
        ("bot", bot, ("NOTEBOOKLM_SERVER_URL", "NOTEBOOKLM_BOT_CALLBACK_KEY")),
    ):
        missing = [name for name in required if not settings.get(name)]
        if missing:
            raise ValueError(f"Preencha a env do {label}: {', '.join(missing)}")
    key = server["NOTEBOOKLM_BOT_CALLBACK_KEY"]
    if len(key) < 32 or key != key.strip():
        raise ValueError("Chave do bot: use pelo menos 32 caracteres aleatorios, sem espacos nas extremidades")
    if not secrets.compare_digest(key.encode(), bot["NOTEBOOKLM_BOT_CALLBACK_KEY"].encode()):
        raise ValueError("As chaves do servidor e do bot devem ser iguais")
    for url in (server["PUBLIC_URL"], bot["NOTEBOOKLM_SERVER_URL"]):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("Use a URL HTTPS raiz, sem credenciais, query, /api ou /mcp")
    if server["PUBLIC_URL"].rstrip("/") != bot["NOTEBOOKLM_SERVER_URL"].rstrip("/"):
        raise ValueError("PUBLIC_URL e NOTEBOOKLM_SERVER_URL devem apontar ao mesmo servidor")
    return server


def database_params(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("DATABASE_URL invalida")
    sslmode = parse_qs(parsed.query).get("sslmode", ["require"])[0]
    if sslmode not in ("require", "verify-ca", "verify-full"):
        raise ValueError("A migracao remota exige sslmode=require, verify-ca ou verify-full")
    # Mesmo formato de senha literal tolerado pelo db.py existente.
    return dict(host=parsed.hostname, port=parsed.port or 5432,
                dbname=parsed.path.lstrip("/"), user=parsed.username,
                password=parsed.password, sslmode=sslmode, connect_timeout=10)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Aplica a migracao no banco configurado")
    args = parser.parse_args(argv)
    try:
        settings = read_settings(ROOT / "server/.env", ROOT / "scripts/bot/.env")
        params = database_params(settings["DATABASE_URL"])
    except ValueError as exc:
        # Mensagens controladas: nunca imprimir valores das envs.
        print(f"Configuracao pendente: {exc}")
        return 1
    if not args.apply:
        print("As duas configuracoes foram validadas. Nenhuma conexao ou alteracao realizada.")
        return 0
    try:
        sql = (ROOT / "server/db/bot_links.sql").read_text(encoding="utf-8")
        with psycopg.connect(**params) as conn:
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute("SET LOCAL statement_timeout = '15s'")
            conn.execute(sql)
            conn.execute("SELECT token_hash, email, expires_at, usado_em, criado_em FROM notebooklm.bot_links LIMIT 0")
    except Exception:
        print("Migracao falhou. Verifique conexao, TLS, permissoes e schema existente. Detalhes omitidos para proteger credenciais.")
        return 1
    print("Migracao bot_links aplicada e verificada. Nenhum token ou usuario alterado.")
    print("O deploy do servidor e a configuracao do bot em producao continuam separados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
