"""Adaptador do backend do bot. Nao captura login nem recebe senha Google."""
import argparse
from getpass import getpass
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dotenv import dotenv_values


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Nunca encaminhar cookies ou X-Bot-Key a outro destino.


def send_token(link_token, google_account, storage_state, env_path=None):
    """Chame apos capturar a sessao e identificar a conta no navegador do bot."""
    settings = dotenv_values(env_path or Path(__file__).with_name(".env"), interpolate=False)
    base = (settings.get("NOTEBOOKLM_SERVER_URL") or "").rstrip("/")
    key = settings.get("NOTEBOOKLM_BOT_CALLBACK_KEY") or ""
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query
            or parsed.fragment or parsed.username or parsed.password or len(key) < 32):
        raise ValueError("Preencha a URL HTTPS raiz e a chave do bot em scripts/bot/.env")
    body = json.dumps({"link_token": link_token, "google_account": google_account,
                       "storage_state": storage_state}).encode()
    if len(body) > 1024 * 1024:
        raise ValueError("Sessao excede 1 MiB")
    req = Request(base + "/api/bot/token", data=body, method="POST",
                  headers={"Content-Type": "application/json", "X-Bot-Key": key})
    try:
        with build_opener(NoRedirect()).open(req, timeout=30) as response:
            result = json.loads(response.read(65536))
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise ValueError("Resposta inesperada do servidor")
            return {"status": "ok"}
    except HTTPError as exc:
        raise RuntimeError(f"Callback recusado (HTTP {exc.code}); resposta omitida") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Falha de rede; verifique /api/auth/check antes de repetir") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-state", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.storage_state.stat().st_size > 1024 * 1024:
            raise ValueError("Arquivo excede o limite")
        state = json.loads(args.storage_state.read_text(encoding="utf-8"))
        code = getpass("Codigo temporario de vinculo (oculto): ")
        account = input("Conta Google identificada no login do bot: ").strip()
        send_token(code, account, state)
    except Exception:
        print("Envio nao confirmado. Verifique configuracao, arquivo e status da sessao; nenhum segredo foi exibido.")
        return 1
    print("Sessao enviada com sucesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
