"""
MCP Server remoto do NotebookLM, com login Google (OAuth).

O Claude conecta colando a URL em Settings -> Connectors -> Add custom connector:
    <PUBLIC_URL>/mcp     (PUBLIC_URL = variavel de ambiente obrigatoria)

O usuario faz login com a conta Google dele. O servidor identifica o email a
partir do token OAuth — nao precisa passar email manualmente. O nivel de acesso
e aplicado a partir do cadastro no Postgres.
"""
import logging
import threading
import time
from collections import defaultdict, deque

from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token
from mcp.server.auth.provider import AccessToken

import rpc
import db
import bot_link
import auth as auth_mod
from config import (
    PUBLIC_URL, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET,
    ALLOWED_EMAIL_DOMAINS, ALLOWED_EMAILS, MCP_RATE_PER_MIN,
)

logger = logging.getLogger(__name__)

# ── Servidor FastMCP com Autenticacao Dual (Google OAuth + Postgres Bearer Token) ──
auth_provider = None
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    auth_provider = GoogleProvider(
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        base_url=PUBLIC_URL,
        required_scopes=["openid", "email", "profile"],
    )
    _original_verify = auth_provider.verify_token

    async def _dual_verify_token(token: str) -> AccessToken | None:
        """
        Aceita tanto o Bearer token do Postgres (usado por IDEs / Antigravity / scripts)
        quanto os tokens de OAuth do Google (usados pelo Claude Web / Connectors).
        """
        # 1. Tenta validar como api_token de usuario no Postgres
        try:
            user = db.get_user_by_token(token)
            if user and user.get("email"):
                email = user["email"].lower()
                return AccessToken(
                    token=token,
                    client_id="postgres_client",
                    scopes=["openid", "email", "profile"],
                    claims={"email": email, "email_verified": True},
                )
        except Exception as e:
            logger.debug("Erro ao verificar token no Postgres: %s", e)

        # 2. Se nao for token do Postgres, repassa para a verificacao original do OAuth Google
        try:
            return await _original_verify(token)
        except Exception:
            return None

    auth_provider.verify_token = _dual_verify_token

mcp = FastMCP("NotebookLM", auth=auth_provider)


def _current_email() -> str | None:
    """
    Extrai o email do usuario a partir do token de acesso (OAuth do Google ou Bearer token do Postgres)
    ou do scope/headers HTTP.
    """
    # 1. Tenta extrair via get_access_token() do FastMCP (suporta OAuth Google e Postgres api_token)
    try:
        token = get_access_token()
        if token is not None:
            claims = getattr(token, "claims", None) or {}
            email = claims.get("email")
            if email:
                email = email.lower()
                if claims.get("email_verified") is False:
                    logger.warning("OAuth: email nao verificado recusado (%s)", email)
                    return None
                if ALLOWED_EMAILS or ALLOWED_EMAIL_DOMAINS:
                    domain = email.rsplit("@", 1)[-1]
                    if email not in ALLOWED_EMAILS and domain not in ALLOWED_EMAIL_DOMAINS:
                        logger.warning("OAuth: email fora da allowlist recusado (%s)", email)
                        return None
                return email
    except (RuntimeError, AttributeError) as e:
        # get_access_token() levanta RuntimeError fora de um contexto de request.
        # Capturar Exception aqui esconderia erro de verdade no caminho de auth.
        logger.debug("get_access_token indisponivel (fora de contexto): %s", e)

    # 2. Fallback: Bearer token direto dos headers HTTP ou scope injetado
    try:
        from fastmcp.server.dependencies import get_http_request
        req = get_http_request()
        if req is not None:
            if getattr(req, "scope", None):
                if req.scope.get("user_email"):
                    return req.scope["user_email"]
                state = req.scope.get("state")
                if isinstance(state, dict) and state.get("user_email"):
                    return state["user_email"]

            if getattr(req, "headers", None):
                auth_hdr = req.headers.get("authorization", "")
                if auth_hdr.startswith("Bearer "):
                    raw_token = auth_hdr.split(" ", 1)[1].strip()
                    if not raw_token:
                        # "Bearer " sem token: nao vale consultar o banco.
                        logger.debug("Authorization: Bearer sem token")
                        return None
                    user = db.get_user_by_token(raw_token)
                    if user and user.get("email"):
                        return user["email"].lower()
    except (RuntimeError, AttributeError) as e:
        # Mesmo motivo do bloco acima: fora de contexto HTTP o fastmcp levanta
        # RuntimeError. Falha do Postgres NAO e capturada aqui de proposito —
        # ela sobe, em vez de virar silenciosamente "nao autenticado".
        logger.debug("Contexto HTTP indisponivel no fallback: %s", e)

    return None





# ── Rate limit por-usuario (janela deslizante de 60s, em memoria por-processo) ────
_rl_lock = threading.Lock()
_rl_calls: dict[str, deque] = defaultdict(deque)


def _client_ip() -> str | None:
    """IP do cliente (best-effort) para correlacao/rastreamento no access_log."""
    try:
        from fastmcp.server.dependencies import get_http_request
        req = get_http_request()
        if req is not None and getattr(req, "client", None) is not None:
            return req.client.host
    except Exception:
        pass
    return None


def _rate_ok(email: str) -> bool:
    """
    True se o email ainda esta dentro do limite (MCP_RATE_PER_MIN/min). O MCP nao
    passa pelo slowapi da REST, entao este e o freio das tools que batem no
    NotebookLM. Fail-open: erro interno nunca derruba uma chamada legitima.
    """
    try:
        now = time.monotonic()
        with _rl_lock:
            dq = _rl_calls[email]
            while dq and now - dq[0] > 60:
                dq.popleft()
            if len(dq) >= MCP_RATE_PER_MIN:
                return False
            dq.append(now)
            return True
    except Exception:
        return True


# ── Ferramentas expostas ao Claude ───────────────────────────────────────────────

@mcp.tool()
async def listar_notebooks() -> list[dict]:
    """Lista os notebooks que voce (usuario logado) pode acessar."""
    email = _current_email()
    if not email:
        return [{"erro": "Nao autenticado"}]
    ip = _client_ip()
    # Gate por "cadastrado e ativo" (nao por hierarquia): financeiro e nivel
    # paralelo — o que cada um ve e decidido pelo filtro por area no rpc.
    if not db.check_active(email):
        db.log_access("listagem", email, ip=ip, resultado="negado", detalhe="nao cadastrado/inativo")
        return [{"erro": f"Usuario {email} nao cadastrado ou inativo"}]
    if not _rate_ok(email):
        db.log_access("listagem", email, ip=ip, resultado="negado", detalhe="rate limit")
        return [{"erro": "Limite de requisicoes atingido; tente novamente em instantes"}]
    db.log_access("listagem", email, ip=ip, session_account=db.get_google_account(email))
    return await rpc.list_notebooks(email)


@mcp.tool()
async def perguntar(notebook_id: str, pergunta: str) -> dict:
    """
    Faz uma pergunta a um notebook do NotebookLM e retorna a resposta com citacoes.

    notebook_id: id do notebook a consultar
    pergunta: a pergunta em linguagem natural
    """
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    ip = _client_ip()
    if not db.check_active(email):
        db.log_access("pergunta", email, ip=ip, notebook_id=notebook_id,
                      resultado="negado", detalhe="nao cadastrado/inativo")
        return {"erro": f"Usuario {email} nao cadastrado ou inativo"}
    if not _rate_ok(email):
        db.log_access("pergunta", email, ip=ip, notebook_id=notebook_id,
                      resultado="negado", detalhe="rate limit")
        return {"erro": "Limite de requisicoes atingido; tente novamente em instantes"}
    db.log_access("pergunta", email, ip=ip, notebook_id=notebook_id,
                  session_account=db.get_google_account(email))
    return await rpc.ask(email, notebook_id, pergunta, ip=ip)


@mcp.tool()
async def listar_fontes(notebook_id: str) -> list[dict]:
    """Lista as fontes indexadas em um notebook."""
    email = _current_email()
    if not email:
        return [{"erro": "Nao autenticado"}]
    ip = _client_ip()
    if not db.check_active(email):
        db.log_access("listar_fontes", email, ip=ip, notebook_id=notebook_id,
                      resultado="negado", detalhe="nao cadastrado/inativo")
        return [{"erro": f"Usuario {email} nao cadastrado ou inativo"}]
    if not _rate_ok(email):
        return [{"erro": "Limite de requisicoes atingido; tente novamente em instantes"}]
    db.log_access("listar_fontes", email, ip=ip, notebook_id=notebook_id,
                  session_account=db.get_google_account(email))
    return await rpc.list_sources(email, notebook_id)


@mcp.tool()
async def criar_notebook(titulo: str) -> dict:
    """
    Cria um novo notebook no NotebookLM (apenas admin).

    titulo: titulo do novo notebook
    """
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    ip = _client_ip()
    if not db.check_access(email, "admin"):
        db.log_access("criacao", email, ip=ip, resultado="negado", detalhe="sem nivel admin")
        return {"erro": f"Apenas admin pode criar notebooks (usuario: {email})"}
    if not _rate_ok(email):
        return {"erro": "Limite de requisicoes atingido; tente novamente em instantes"}
    db.log_access("criacao", email, ip=ip, detalhe=f"titulo={titulo}")
    return await rpc.create_notebook(email, titulo)


@mcp.tool()
async def adicionar_fonte(
    notebook_id: str,
    url: str | None = None,
    drive_file_id: str | None = None,
    titulo: str | None = None,
    mime_type: str = "application/vnd.google-apps.document",
) -> dict:
    """
    Adiciona uma fonte a um notebook (gestor ou admin). Informe `url` OU
    `drive_file_id` (com `titulo` obrigatorio para Drive).

    url: link publico da fonte (pagina, PDF online, YouTube)
    drive_file_id: id de arquivo no Google Drive
    titulo: titulo de exibicao (obrigatorio para fonte do Drive)
    mime_type: tipo do arquivo Drive (Docs por padrao; use application/pdf para PDF)
    """
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    ip = _client_ip()
    if not db.check_access(email, "gestor"):
        db.log_access("add_fonte", email, ip=ip, notebook_id=notebook_id,
                      resultado="negado", detalhe="sem nivel gestor")
        return {"erro": f"Apenas gestor ou admin pode adicionar fontes (usuario: {email})"}
    if not _rate_ok(email):
        return {"erro": "Limite de requisicoes atingido; tente novamente em instantes"}
    db.log_access("add_fonte", email, ip=ip, notebook_id=notebook_id,
                  detalhe=(url or f"drive:{drive_file_id}"))
    if bool(url) == bool(drive_file_id):
        return {"erro": "Informe exatamente um: url ou drive_file_id"}
    if url:
        return await rpc.add_source_url(email, notebook_id, url)
    if not titulo:
        return {"erro": "titulo e obrigatorio para fonte do Google Drive"}
    return await rpc.add_source_drive(email, notebook_id, drive_file_id, titulo, mime_type)


@mcp.tool()
async def criar_vinculo_bot() -> dict:
    """Gera codigo de uso unico (10 min) para o bot enviar SUA sessao Google.

    Nao recebe email nem cookies. Entregue apenas o codigo ao bot confiavel.
    """
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    if not _rate_ok(email):
        return {"erro": "Limite de requisicoes atingido"}
    try:
        return bot_link.issue_link(email)
    except PermissionError as exc:
        return {"erro": str(exc)}


@mcp.tool()
async def verificar_token() -> dict:
    """Verifica se o seu token Google do NotebookLM esta valido."""
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    if not _rate_ok(email):
        return {"erro": "Limite de requisicoes atingido; tente novamente em instantes"}
    return await auth_mod.check_auth(email)


@mcp.tool()
async def renovar_token() -> dict:
    """Forca um keep-alive no Google NotebookLM e persiste os cookies renovados no Postgres."""
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    if not _rate_ok(email):
        return {"erro": "Limite de requisicoes atingido; tente novamente em instantes"}
    return await auth_mod.renovar_token(email)



@mcp.tool()
async def quem_sou_eu() -> dict:
    """Retorna o email e o nivel de acesso do usuario logado."""
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    user = db.get_user(email)
    if not user:
        return {"email": email, "cadastrado": False,
                "aviso": "Voce esta autenticado mas ainda nao tem token do NotebookLM registrado. Rode o conector connect.py."}
    return {"email": email, "cadastrado": True, "nivel": user["nivel"], "ativo": user["ativo"]}


@mcp.tool()
async def listar_compartilhados() -> list[dict]:
    """
    Lista os notebooks que voce acessa, marcando quais sao SEUS (`meu`) e quais
    sao COMPARTILHADOS com voce (`compartilhado`) — e DE QUEM cada um e.
    """
    email = _current_email()
    if not email:
        return [{"erro": "Nao autenticado"}]
    ip = _client_ip()
    if not db.check_active(email):
        db.log_access("listar_compartilhados", email, ip=ip, resultado="negado",
                      detalhe="nao cadastrado/inativo")
        return [{"erro": f"Usuario {email} nao cadastrado ou inativo"}]
    if not _rate_ok(email):
        return [{"erro": "Limite de requisicoes atingido; tente novamente em instantes"}]
    db.log_access("listar_compartilhados", email, ip=ip,
                  session_account=db.get_google_account(email))
    return await rpc.list_shared(email)


@mcp.tool()
async def compartilhar_notebook(notebook_id: str, email_destino: str,
                                permissao: str = "viewer", notificar: bool = True,
                                nivel_visao: str | None = None) -> dict:
    """
    Compartilha um notebook com um usuario (apenas admin).

    permissao: 'viewer' (so leitura) ou 'editor'.
    nivel_visao (opcional; afeta o notebook TODO): 'completo' ou 'chat'
        ('chat' = o destinatario so consulta, sem ver/baixar as fontes).
    """
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    ip = _client_ip()
    if not db.check_access(email, "admin"):
        db.log_access("compartilhar", email, ip=ip, notebook_id=notebook_id,
                      resultado="negado", detalhe="sem nivel admin")
        return {"erro": f"Apenas admin pode compartilhar (usuario: {email})"}
    if not _rate_ok(email):
        return {"erro": "Limite de requisicoes atingido; tente novamente em instantes"}
    db.log_access("compartilhar", email, ip=ip, notebook_id=notebook_id,
                  detalhe=f"-> {email_destino} ({permissao})")
    return await rpc.share_notebook(email, notebook_id, email_destino,
                                    permissao, notificar, nivel_visao)


@mcp.tool()
async def status_compartilhamento(notebook_id: str) -> dict:
    """Mostra com quem um notebook esta compartilhado (email, nome e permissao)."""
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    ip = _client_ip()
    if not db.check_active(email):
        return {"erro": f"Usuario {email} nao cadastrado ou inativo"}
    if not _rate_ok(email):
        return {"erro": "Limite de requisicoes atingido; tente novamente em instantes"}
    db.log_access("status_compartilhamento", email, ip=ip, notebook_id=notebook_id,
                  session_account=db.get_google_account(email))
    return await rpc.share_status(email, notebook_id)


@mcp.tool()
async def sincronizar_compartilhamentos(limite: int | None = None) -> dict:
    """
    Varre os notebooks do admin, registra o DONO de cada um e reconstroi 'quem ve
    cada notebook' na nossa base (alimenta o painel e o 'de quem e'). Apenas admin.
    Pode ser lento (1 chamada por notebook) — use `limite` para testar.
    """
    email = _current_email()
    if not email:
        return {"erro": "Nao autenticado"}
    if not db.check_access(email, "admin"):
        return {"erro": f"Apenas admin pode sincronizar (usuario: {email})"}
    ip = _client_ip()
    db.log_access("sync_compartilhamentos", email, ip=ip, detalhe=f"limite={limite}")
    return await rpc.sync_shares(email, limite)


class BearerOrOAuthMiddleware:
    """
    Middleware ASGI que identifica o Bearer Token do usuario no Postgres e injeta
    a identidade (email) no scope da requisicao para todas as chamadas do FastMCP.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            auth_hdr = headers.get(b"authorization", b"").decode("utf-8")
            if auth_hdr.startswith("Bearer "):
                token_str = auth_hdr.split(" ", 1)[1].strip()
                user = db.get_user_by_token(token_str)
                if user and user.get("email"):
                    email = user["email"].lower()
                    scope["user_email"] = email
                    if "state" not in scope or not isinstance(scope["state"], dict):
                        scope["state"] = {}
                    scope["state"]["user_email"] = email

        await self.app(scope, receive, send)



# App ASGI do MCP (Streamable HTTP). Servido no root para que os endpoints
# OAuth (/.well-known, /authorize, /auth/callback) fiquem acessiveis.
_raw_mcp_app = mcp.http_app(path="/mcp")
mcp_app = BearerOrOAuthMiddleware(_raw_mcp_app)

if __name__ == "__main__":
    mcp.run()


