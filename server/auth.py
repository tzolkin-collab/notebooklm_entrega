"""
Autenticacao: busca token do usuario no Postgres, descriptografa e retorna cliente NotebookLM.
"""
import logging
import tempfile
import json
import pathlib
from contextlib import asynccontextmanager

from notebooklm import NotebookLMClient

import db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_client_for(email: str):
    """
    Retorna um cliente NotebookLM autenticado com o token do usuario.
    Busca o storage_state no Postgres, salva temporariamente, inicializa o cliente,
    e ao final salva automaticamente quaisquer cookies novos/renovados pelo Google.
    """
    state = db.get_storage_state(email)

    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = pathlib.Path(tmpdir) / "storage_state.json"
        state_path.touch(mode=0o600)
        state_path.write_text(json.dumps(state))

        async with NotebookLMClient.from_storage(path=str(state_path)) as client:
            yield client

        # Apos o uso, verifica se o cliente atualizou o storage_state (ex.: cookies de sessao SIDTS rotacionados)
        try:
            if state_path.exists():
                new_state = json.loads(state_path.read_text(encoding="utf-8"))
                if new_state != state:
                    db.save_storage_state(email, new_state)
                    logger.info("Cookies de %s atualizados e salvos automaticamente no Postgres.", email)
        except Exception as e:
            logger.warning("Falha ao salvar cookies atualizados de %s: %s", email, e)


async def check_auth(email: str) -> dict:
    """
    Testa se o token do usuario ainda autentica de verdade no Google.
    """
    try:
        db.get_storage_state(email)
    except ValueError as e:
        return {"status": "error", "email": email, "detail": str(e)}

    try:
        async with get_client_for(email) as client:
            await client.notebooks.list()
        return {"status": "ok", "email": email, "detalhe": "Sessao ativa e token renovado no banco."}
    except Exception as e:
        msg = str(e)
        if "accounts.google.com" in msg or "expired" in msg.lower() or "invalid" in msg.lower():
            return {
                "status": "expired",
                "email": email,
                "detail": "Token expirado — refaca o login para renovar.",
            }
        logger.error("Auth check falhou para %s: %s", email, e)
        return {"status": "error", "email": email, "detail": msg}


async def renovar_token(email: str) -> dict:
    """
    Forca uma chamada de keep-alive no Google NotebookLM para renovar e persistir os cookies no Postgres.
    """
    return await check_auth(email)

