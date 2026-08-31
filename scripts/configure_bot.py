"""Valida as duas envs do fluxo do bot sem exibir segredos.

A migracao da tabela notebooklm.bot_links deixou de ser manual: o Dockerfile
roda `python db/apply_schema.py` (idempotente) a cada start do container, e
schema.sql ja inclui bot_links. Este script so confere se as duas envs
(server/.env e scripts/bot/.env) estao coerentes entre si -- nunca conecta
no banco.
"""
import argparse
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def read_settings(server_path, bot_path):
    server = dotenv_values(server_path, interpolate=False)
    bot = dotenv_values(bot_path, interpolate=False)
    for label, settings, required in (
        ("servidor", server, ("PUBLIC_URL", "NOTEBOOKLM_BOT_CALLBACK_KEY")),
        ("bot", bot, ("NOTEBOOKLM_SERVER_URL", "NOTEBOOKLM_BOT_CALLBACK_KEY")),
    ):
        missing = [name for name in required if not settings.get(name)]
        if missing:
            raise ValueError(f"Preencha a env do {label}: {', '.join(missing)}")
    key = server["NOTEBOOKLM_BOT_CALLBACK_KEY"]
    if len(key) < 32 or key != key.strip():
        raise ValueError("Chave do bot: use pelo menos 32 caracteres aleatorios, sem espacos nas extremidades")
    if key != bot["NOTEBOOKLM_BOT_CALLBACK_KEY"]:
        raise ValueError("As chaves do servidor e do bot devem ser iguais")
    for url in (server["PUBLIC_URL"], bot["NOTEBOOKLM_SERVER_URL"]):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("Use a URL HTTPS raiz, sem credenciais, query, /api ou /mcp")
    if server["PUBLIC_URL"].rstrip("/") != bot["NOTEBOOKLM_SERVER_URL"].rstrip("/"):
        raise ValueError("PUBLIC_URL e NOTEBOOKLM_SERVER_URL devem apontar ao mesmo servidor")
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        read_settings(ROOT / "server/.env", ROOT / "scripts/bot/.env")
    except ValueError as exc:
        # Mensagens controladas: nunca imprimir valores das envs.
        print(f"Configuracao pendente: {exc}")
        return 1
    print("As duas configuracoes foram validadas. Nenhuma conexao ou alteracao realizada.")
    print("A migracao de bot_links e automatica no deploy (Dockerfile roda db/apply_schema.py).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
