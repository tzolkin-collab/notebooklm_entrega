"""
Entry point do servidor — combina o MCP (raiz, com OAuth) e a API REST (/api).

- MCP / conector do Claude:  https://<host>/mcp
- Endpoints OAuth:           https://<host>/.well-known/...  /authorize  /auth/callback
- API REST (n8n, connect.py): https://<host>/api/...
- Health:                    https://<host>/api/health  e  https://<host>/health

Rodar:  uvicorn main:app --host 0.0.0.0 --port 80
"""
import logging

from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_server import _raw_mcp_app, BearerOrOAuthMiddleware
from api import app as rest_app

logging.basicConfig(level=logging.INFO)

# O MCP e o app raiz (Starlette). Montamos a API REST em /api.
_raw_mcp_app.mount("/api", rest_app)


# Health no root tambem, para o EasyPanel checar facil
async def _health(request):
    return JSONResponse({"status": "ok"})

_raw_mcp_app.router.routes.append(Route("/health", _health, methods=["GET"]))

# App final com middleware de autenticação Bearer por-usuário
app = BearerOrOAuthMiddleware(_raw_mcp_app)
