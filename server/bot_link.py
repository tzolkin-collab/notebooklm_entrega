"""Contrato compartilhado pela API REST e pela emissao via MCP."""
import os

import db
from config import PUBLIC_URL


def bot_key() -> str:
    return os.getenv("NOTEBOOKLM_BOT_CALLBACK_KEY", "").strip()


def issue_link(email: str) -> dict:
    if not bot_key():
        raise PermissionError("Integracao do bot desabilitada")
    return {
        "link_token": db.create_bot_link(email),
        "expires_in": 600,
        "callback_url": PUBLIC_URL.rstrip("/") + "/api/bot/token",
    }
