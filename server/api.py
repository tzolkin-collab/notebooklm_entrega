import logging
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request, Security, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import rpc
import auth
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Teto global, aplicado ANTES da autenticacao ──────────────────────────────────
#
# O @limiter.limit() do slowapi decora a funcao da rota, mas o FastAPI resolve as
# dependencias antes de chama-la: nos endpoints com Depends(auth), o 401 acontece
# antes de o contador existir. Verificado contra o deploy real — 13 requisicoes
# sem credencial em /api/auth/check, nenhum 429.
#
# O SlowAPIMiddleware NAO resolve isso, apesar de parecer a correcao obvia. O
# _should_exempt dele tem:
#
#     # there is a decorator for this route we let the decorator handle it
#     if name in limiter._route_limits: return True
#
# Ou seja: ele pula de proposito justamente as rotas decoradas, que sao as
# quebradas. Testado antes de entender o porque — o middleware rodava e nao
# limitava nada.
#
# Dai este middleware proprio: janela deslizante por IP, avaliada antes de
# qualquer rota. Os limites por rota do slowapi continuam valendo para quem
# passou da autenticacao; este e so o teto de abuso.
#
# Mesma limitacao do _rate_ok do MCP: contagem EM MEMORIA, por processo. Correto
# com 1 worker (o Dockerfile nao passa --workers). Escalar exige backend
# compartilhado nos dois lugares.
RATE_GLOBAL = int(os.getenv("NOTEBOOKLM_RATE_GLOBAL_POR_MIN", "120"))

_rl_lock = threading.Lock()
_rl_hits: dict[str, deque] = defaultdict(deque)


# /health fica de fora: o HEALTHCHECK do container bate nele a cada 30s. Sob
# carga alta, limitar o proprio healthcheck faria o container ser marcado
# unhealthy e reiniciar — transformando excesso de trafego em queda do servico,
# que e o oposto do que um rate limit existe para fazer.
ISENTOS = {"/health", "/api/health"}


class TetoGlobalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ISENTOS:
            return await call_next(request)
        ip = request.client.host if request.client else "desconhecido"
        agora = time.monotonic()
        try:
            with _rl_lock:
                dq = _rl_hits[ip]
                while dq and agora - dq[0] > 60:
                    dq.popleft()
                if len(dq) >= RATE_GLOBAL:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": f"Limite de {RATE_GLOBAL} requisicoes por minuto atingido."},
                    )
                dq.append(agora)
        except Exception:
            # Fail-open: falha interna do contador nunca derruba trafego legitimo.
            logger.exception("teto global falhou; seguindo sem limitar")
        return await call_next(request)


limiter = Limiter(key_func=get_remote_address)
# API REST (usada pelo n8n e pelas ferramentas admin). Montada em /api pelo main.py.
# O MCP (mcp_server) e o app raiz para que o OAuth funcione no root.
# openapi_url=None junto com docs_url/redoc_url: desligar so a UI deixa o schema
# em /openapi.json, publico e sem autenticacao — o mapa completo da API (rotas,
# parametros, esquema de auth) para quem nao passou por autenticacao nenhuma.
# Verificado num deploy real: /docs dava 404, /openapi.json dava 200.
app = FastAPI(title="NotebookLM Connector", docs_url=None, redoc_url=None, openapi_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(TetoGlobalMiddleware)


@app.exception_handler(PermissionError)
async def _permission_error_handler(request: Request, exc: PermissionError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _sem_sessao_handler(request: Request, exc: ValueError):
    """
    Usuario autenticado e ativo, mas sem sessao Google no banco.

    Sem isto o caminho devolvia 500 Internal Server Error — verificado contra a
    instancia real: GET /notebooks com Bearer valido e sem storage_state dava
    500, enquanto /auth/check (que trata a excecao) respondia direito.

    Afetava os seis endpoints que passam por rpc.*, e o estado e comum: qualquer
    pessoa ativada antes de rodar o connect.py, ou cuja sessao foi removida, caia
    nele. "Internal Server Error" nao diz a ninguem o que fazer.

    409 e nao 401/403: a credencial da API esta correta e o nivel tambem — o que
    falta e um pre-requisito de estado. Tratar como falha de autenticacao mandaria
    a pessoa procurar o problema no lugar errado.

    O unico `raise ValueError` do servidor e o de sessao ausente (db.py). Se
    outro aparecer, este handler passa a mascara-lo: crie uma excecao propria.
    """
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(exc),
            "acao": "Rode client/connect.py para enviar sua sessao Google, "
                    "ou peca ao admin um token de onboarding.",
        },
    )


# ── Autenticacao ────────────────────────────────────────────────────────────────
# Dois mecanismos, deliberadamente separados:
#   • Token de onboarding POR-USUARIO (X-Onboarding-Token) -> SOMENTE para o
#     bootstrap /token/upload. Uso unico, ligado a um email, emitido por um admin.
#     Substitui a antiga connector key compartilhada: um token vazado so serve
#     para o email a que foi emitido, e so uma vez.
#   • Bearer token por-usuario -> todos os endpoints de dados. A identidade
#     (email + nivel) vem do token no banco, NUNCA de um header espoofavel.

bearer_scheme = HTTPBearer(auto_error=True)


def current_user(creds: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> dict:
    """
    Identifica o usuario pelo token Bearer por-usuario. get_user_by_token ja
    filtra `ativo=true`, entao um token de usuario inativo/desconhecido falha aqui.
    """
    user = db.get_user_by_token(creds.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Token de usuario invalido ou inativo")
    return user


def require_active_user(user: dict = Depends(current_user)) -> dict:
    """
    Operacoes de consulta: exige apenas usuario ativo. Financeiro e nivel
    PARALELO (nao inferior) — o que cada um ve e decidido pelo filtro por area
    no rpc (fail-closed).
    """
    return user


def require_nivel(nivel_minimo: str):
    """Dependencia que verifica nivel minimo do usuario (derivado do token)."""
    def check(user: dict = Depends(current_user)) -> dict:
        if not db.nivel_atende(user["nivel"], nivel_minimo):
            raise HTTPException(
                status_code=403,
                detail=f"Acesso negado. Seu nivel: {user['nivel']}. Necessario: {nivel_minimo}",
            )
        return user
    return check


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/check")
@limiter.limit("10/minute")
async def auth_check(request: Request, user: dict = Depends(require_active_user)):
    return await auth.check_auth(user["email"])


# ── Notebooks ─────────────────────────────────────────────────────────────────

@app.get("/notebooks")
@limiter.limit("30/minute")
async def list_notebooks(request: Request, user: dict = Depends(require_active_user)):
    return await rpc.list_notebooks(user["email"])


class CreateNotebookRequest(BaseModel):
    title: str


@app.post("/notebooks")
@limiter.limit("10/minute")
async def create_notebook(request: Request, body: CreateNotebookRequest,
                          user: dict = Depends(require_nivel("admin"))):
    return await rpc.create_notebook(user["email"], body.title)


# ── Fontes ────────────────────────────────────────────────────────────────────

@app.get("/notebooks/{notebook_id}/sources")
@limiter.limit("30/minute")
async def list_sources(request: Request, notebook_id: str,
                       user: dict = Depends(require_active_user)):
    return await rpc.list_sources(user["email"], notebook_id)


class AddSourceRequest(BaseModel):
    url: str | None = None
    drive_file_id: str | None = None
    titulo: str | None = None
    mime_type: str = "application/vnd.google-apps.document"


@app.post("/notebooks/{notebook_id}/sources")
@limiter.limit("10/minute")
async def add_source(request: Request, notebook_id: str, body: AddSourceRequest,
                     user: dict = Depends(require_nivel("gestor"))):
    if bool(body.url) == bool(body.drive_file_id):
        raise HTTPException(status_code=400, detail="Informe exatamente um: url ou drive_file_id")
    if body.url:
        return await rpc.add_source_url(user["email"], notebook_id, body.url)
    if not body.titulo:
        raise HTTPException(status_code=400, detail="titulo e obrigatorio para fonte do Google Drive")
    return await rpc.add_source_drive(user["email"], notebook_id, body.drive_file_id, body.titulo, body.mime_type)


# ── Chat ──────────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    source_ids: list[str] | None = None


@app.post("/notebooks/{notebook_id}/ask")
@limiter.limit("20/minute")
async def ask(request: Request, notebook_id: str, body: AskRequest,
              user: dict = Depends(require_active_user)):
    ip = request.client.host if request.client else None
    db.log_access("pergunta", user["email"], ip=ip, notebook_id=notebook_id,
                  session_account=db.get_google_account(user["email"]), detalhe="via REST")
    return await rpc.ask(user["email"], notebook_id, body.question, body.source_ids, ip=ip)


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/team")
@limiter.limit("10/minute")
async def team_status(request: Request, user: dict = Depends(require_nivel("admin"))):
    """Lista usuarios e status de tokens (apenas admin)."""
    return db.list_team()


class NotebookClassificacao(BaseModel):
    id: str
    titulo: str = ""
    area: str  # juridico | financeiro | comercial


class ClassificarRequest(BaseModel):
    notebooks: list[NotebookClassificacao]


@app.post("/admin/notebooks-classificacao")
@limiter.limit("10/minute")
async def classificar_notebooks(request: Request, body: ClassificarRequest,
                                user: dict = Depends(require_nivel("admin"))):
    """
    Upsert da classificacao de notebooks por area (tabela notebooklm.notebooks).
    Alimentado pelo script scripts/classifica_notebooks.py apos revisao humana.
    """
    gravados = db.upsert_notebooks([n.model_dump() for n in body.notebooks])
    return {"status": "ok", "gravados": gravados, "recebidos": len(body.notebooks)}


class ActivateUserRequest(BaseModel):
    email: str
    nivel: str
    ativo: bool = True


@app.post("/admin/users")
@limiter.limit("10/minute")
async def admin_set_user(request: Request, body: ActivateUserRequest,
                         admin: dict = Depends(require_nivel("admin"))):
    """
    Ativa/define o nivel de um usuario e emite (rotaciona) o token Bearer
    por-usuario que ele usara na API REST. Este e o UNICO caminho para conceder
    nivel — fecha o escalonamento de privilegio do /token/upload (que so cria
    cadastro pendente). O usuario precisa existir (rodou connect.py antes).
    """
    if body.nivel not in ("admin", "gestor", "juridico", "financeiro"):
        raise HTTPException(status_code=400, detail="Nivel invalido")
    if not db.set_user_nivel_ativo(body.email, body.nivel, body.ativo):
        raise HTTPException(
            status_code=404,
            detail=f"Usuario {body.email} nao encontrado — peca a ele para rodar connect.py primeiro.",
        )
    token = db.issue_api_token(body.email) if body.ativo else None
    logger.info("admin %s definiu %s -> nivel=%s ativo=%s", admin["email"], body.email, body.nivel, body.ativo)
    return {
        "status": "ok",
        "email": body.email,
        "nivel": body.nivel,
        "ativo": body.ativo,
        "api_token": token,
        "aviso": (
            "Guarde o api_token com cuidado: e o segredo do usuario na API REST "
            "(envie como 'Authorization: Bearer <token>'). Ele nao sera exibido de novo."
            if token else "Usuario desativado; token nao emitido."
        ),
    }


# ── Onboarding token (admin emite; substitui a connector key compartilhada) ─────

class OnboardingTokenRequest(BaseModel):
    email: str
    ttl_horas: int = 48


@app.post("/admin/onboarding-token")
@limiter.limit("10/minute")
async def admin_onboarding_token(request: Request, body: OnboardingTokenRequest,
                                 admin: dict = Depends(require_nivel("admin"))):
    """
    Emite um token de onboarding de USO ÚNICO, ligado a um email, para o usuario
    subir o token Google via connect.py. Substitui a connector key compartilhada:
    um token vazado só serve para este email e uma vez.
    """
    if not (1 <= body.ttl_horas <= 720):
        raise HTTPException(status_code=400, detail="ttl_horas deve estar entre 1 e 720")
    token = db.create_onboarding_token(body.email, admin["email"], body.ttl_horas)
    logger.info("admin %s emitiu onboarding token para %s (ttl=%sh)",
                admin["email"], body.email, body.ttl_horas)
    db.log_access("onboarding_emitido", admin["email"],
                  ip=(request.client.host if request.client else None),
                  detalhe=f"alvo={body.email} ttl={body.ttl_horas}h")
    return {
        "status": "ok",
        "email": body.email,
        "onboarding_token": token,
        "expira_em_horas": body.ttl_horas,
        "aviso": ("Token de uso único, ligado a este email. Entregue com segurança; "
                  "some após o uso ou a expiração."),
    }


# ── Conector: upload de token (bootstrap) ────────────────────────────────────────

class TokenUploadRequest(BaseModel):
    email: str
    nome: str = ""
    storage_state: dict
    google_account: str | None = None  # conta Google real do login (reportada pelo app)


@app.post("/token/upload")
@limiter.limit("10/minute")
async def token_upload(request: Request, body: TokenUploadRequest,
                       x_onboarding_token: str | None = Header(None, alias="X-Onboarding-Token")):
    """
    Recebe o storage_state de um login Google, salva o token criptografado e
    cria/atualiza o usuario PENDENTE (inativo, sem privilegio). A ativacao e o
    nivel sao decididos por um admin via POST /admin/users.

    Autorizado por um TOKEN DE ONBOARDING de uso único, ligado ao email e emitido
    por um admin (POST /admin/onboarding-token). O token é consumido de forma
    atômica: um vazamento só serve para o email a que foi emitido, e uma só vez.

    `nivel` NAO e aceito aqui: aceitar nivel do corpo era o vetor de escalonamento
    de privilegio (quem tivesse a key se cadastrava como admin).
    """
    cookies = body.storage_state.get("cookies", [])
    google_cookies = [c for c in cookies if "google" in c.get("domain", "")]
    if not google_cookies:
        # Valida o corpo ANTES de consumir o token, para nao queimar o onboarding
        # token do usuario por causa de um upload malformado.
        raise HTTPException(status_code=400, detail="storage_state sem cookies Google validos")

    ip = request.client.host if request.client else None
    if not x_onboarding_token:
        raise HTTPException(status_code=403, detail="Token de onboarding ausente (peça um ao admin)")
    if not db.consume_onboarding_token(x_onboarding_token, body.email):
        db.log_access("onboarding_consumido", body.email, ip=ip, resultado="negado",
                      detalhe="token invalido/expirado/ja usado")
        raise HTTPException(
            status_code=403,
            detail="Token de onboarding inválido, expirado, já usado ou não corresponde ao email",
        )

    # Correlacao/deteccao: a conta Google reportada pelo app deve bater com o
    # cadastro. Se divergir, registra como suspeito (nao bloqueia — o admin decide).
    resultado = "ok"
    if body.google_account and body.google_account.lower() != body.email.lower():
        resultado = "suspeito"
        logger.warning(
            "SECURITY: sessao enviada com conta Google (%s) != cadastro (%s).",
            body.google_account, body.email,
        )

    # Deteccao: se o email ja era um usuario ATIVO, o token dele esta sendo
    # substituido (refresh legitimo ou nao).
    existente = db.get_user(body.email)
    if existente and existente.get("ativo"):
        logger.warning(
            "SECURITY: /token/upload substituindo token de usuario ATIVO (%s). "
            "Confirme que foi um refresh autorizado.", body.email
        )

    novo = db.upsert_self_service_user(body.email, body.nome)
    db.save_storage_state(body.email, body.storage_state, google_account=body.google_account)
    db.log_access("sessao_enviada", body.email, session_account=body.google_account,
                  ip=ip, resultado=resultado,
                  detalhe=("cadastro novo" if novo else "atualizacao"))
    logger.info("Token recebido via conector para %s (novo=%s)", body.email, novo)
    return {
        "status": "ok",
        "email": body.email,
        "cookies": len(google_cookies),
        "pendente_ativacao": novo,
        "aviso": (
            "Cadastro recebido. Um admin precisa ATIVAR seu acesso (POST /admin/users) "
            "e te enviar o token de API."
            if novo else "Token atualizado."
        ),
    }
