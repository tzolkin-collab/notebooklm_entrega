"""
Camada de acesso ao Postgres — gerencia usuarios, tokens e audit log.
"""
import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote

import psycopg
from cryptography.fernet import Fernet

from config import DATABASE_URL, ENCRYPTION_KEY

logger = logging.getLogger(__name__)
_fernet = Fernet(ENCRYPTION_KEY.encode())


def _hash_token(token: str) -> str:
    """
    SHA-256 hex do token Bearer. Guardamos SÓ o hash no banco — o token em
    claro nunca toca o Postgres. Quem só tem a DATABASE_URL não consegue usar
    a coluna api_token como credencial, e a comparação por hash é uniforme.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _db_params() -> dict:
    """Parse da DATABASE_URL tolerante a caracteres especiais nao-encoded na senha.

    psycopg.connect(url) falha com 'invalid percent-encoded token' quando a senha
    contem % literal. urlparse separa user/host/senha corretamente mesmo com @ e %
    literais na senha; passamos os params raw (sem unquote) porque a URL fornecida
    pelo EasyPanel ja vem com a senha literal, nao percent-encoded.
    """
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
        # TLS desligado explicitamente — so aceitavel em rede interna isolada.
        logger.warning(
            "DATABASE_URL com sslmode=disable: trafego app<->Postgres SEM TLS. "
            "Use sslmode=require fora de uma rede interna confiavel."
        )
        params["sslmode"] = "disable"
    elif "sslmode=" not in query:
        # Fail-secure: exige TLS quando o sslmode nao foi especificado.
        params["sslmode"] = "require"
    return {k: v for k, v in params.items() if v is not None}


def _conn():
    return psycopg.connect(**_db_params())


# ── Tokens ────────────────────────────────────────────────────────────────────

def get_storage_state(email: str) -> dict:
    """Retorna o storage_state descriptografado para o email informado."""
    with _conn() as conn:
        cur = conn.execute(
            "SELECT storage_state FROM notebooklm.tokens WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Token nao encontrado para {email}")
    return json.loads(_fernet.decrypt(row[0].encode()).decode())


def save_storage_state(email: str, state: dict, google_account: str | None = None) -> None:
    """
    Criptografa e salva/atualiza o storage_state de um usuario. `google_account`
    e a conta Google real dona da sessao (reportada pelo app no login) — base da
    correlacao cadastro (email) x conta acessada.
    """
    encrypted = _fernet.encrypt(json.dumps(state).encode()).decode()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO notebooklm.tokens (email, storage_state, google_account, atualizado_em)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (email) DO UPDATE
              SET storage_state = EXCLUDED.storage_state,
                  google_account = COALESCE(EXCLUDED.google_account, notebooklm.tokens.google_account),
                  atualizado_em = now()
            """,
            (email, encrypted, google_account),
        )
        conn.commit()


def get_google_account(email: str) -> str | None:
    """Conta Google dona da sessao guardada para `email` (ou None)."""
    with _conn() as conn:
        cur = conn.execute(
            "SELECT google_account FROM notebooklm.tokens WHERE email = %s", (email,)
        )
        row = cur.fetchone()
    return row[0] if row else None


def create_bot_link(email: str) -> str:
    """Codigo de uso unico; a identidade vem da sessao autenticada, nao do bot."""
    token = "link_" + secrets.token_urlsafe(32)
    with _conn() as conn:
        row = conn.execute(
            """INSERT INTO notebooklm.bot_links (token_hash, email, expires_at)
               SELECT %s, email, now() + interval '10 minutes'
                 FROM notebooklm.users WHERE email = %s AND ativo = true
               RETURNING email""",
            (_hash_token(token), email),
        ).fetchone()
        if not row:
            raise PermissionError("Usuario inexistente ou inativo")
    return token


def save_bot_storage_state(token: str, state: dict, google_account: str) -> str | None:
    """Consome o vinculo e salva com Fernet NA MESMA transacao.

    Falha no INSERT desfaz o consumo. UPDATE serializa callbacks concorrentes.
    A conta Google reportada e uma declaracao do bot confiavel, nao prova OAuth.
    """
    encrypted = _fernet.encrypt(json.dumps(state).encode()).decode()
    with _conn() as conn:
        row = conn.execute(
            """UPDATE notebooklm.bot_links AS link SET usado_em = now()
               WHERE token_hash = %s AND usado_em IS NULL AND expires_at > now()
                 AND lower(link.email) = %s
                 AND EXISTS (SELECT 1 FROM notebooklm.users AS u
                             WHERE u.email = link.email AND u.ativo = true)
               RETURNING email""",
            (_hash_token(token), google_account),
        ).fetchone()
        if not row:
            return None
        email = row[0]
        conn.execute(
            """INSERT INTO notebooklm.tokens (email, storage_state, google_account, atualizado_em)
               VALUES (%s, %s, %s, now())
               ON CONFLICT (email) DO UPDATE SET storage_state = EXCLUDED.storage_state,
                   google_account = EXCLUDED.google_account, atualizado_em = now()""",
            (email, encrypted, google_account),
        )
        conn.execute(
            """INSERT INTO notebooklm.access_log (evento, identity_email, session_account, detalhe)
               VALUES ('sessao_enviada', %s, %s, 'via bot; vinculo de uso unico')""",
            (email, google_account),
        )
    return email


# ── Onboarding tokens (uso único, por-usuário) ───────────────────────────────────

def create_onboarding_token(email: str, criado_por: str, ttl_horas: int = 48) -> str:
    """
    Emite um token de onboarding de USO ÚNICO ligado a um email, válido por
    `ttl_horas`. Guarda só o hash; retorna o token em claro UMA vez. Substitui a
    connector key compartilhada: um token vazado só serve para este email e uma vez.
    """
    token = "onb_" + secrets.token_urlsafe(32)
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO notebooklm.onboarding_tokens (token_hash, email, criado_por, expires_at)
            VALUES (%s, %s, %s, now() + make_interval(hours => %s))
            """,
            (_hash_token(token), email, criado_por, ttl_horas),
        )
        conn.commit()
    return token


def consume_onboarding_token(token: str, email: str) -> bool:
    """
    Valida e CONSOME (single-use) um token de onboarding, atomicamente. Só
    sucede se o token existir, corresponder ao `email`, não ter sido usado e não
    estar expirado. Retorna True se consumiu, False caso contrário.
    """
    if not token:
        return False
    with _conn() as conn:
        cur = conn.execute(
            """
            UPDATE notebooklm.onboarding_tokens
               SET usado_em = now()
             WHERE token_hash = %s AND email = %s
               AND usado_em IS NULL AND expires_at > now()
            RETURNING token_hash
            """,
            (_hash_token(token), email),
        )
        row = cur.fetchone()
        conn.commit()
    return row is not None


# ── Usuarios ──────────────────────────────────────────────────────────────────

def upsert_self_service_user(email: str, nome: str) -> bool:
    """
    Cadastro self-service (via /token/upload). Cria o usuario PENDENTE: nivel
    default e `ativo=false`. NUNCA altera nivel/ativo de usuario ja existente —
    so atualiza o nome. Retorna True se criou um cadastro novo (pendente de
    ativacao por um admin), False se o usuario ja existia.

    Este e o ponto que fecha o escalonamento de privilegio: ninguem se
    auto-promove pelo upload; ativacao e nivel sao decisao de um admin
    (POST /admin/users).
    """
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO notebooklm.users (email, nome, nivel, ativo)
            VALUES (%s, %s, 'juridico', false)
            ON CONFLICT (email) DO UPDATE
              SET nome = COALESCE(NULLIF(EXCLUDED.nome, ''), notebooklm.users.nome)
            RETURNING (xmax = 0) AS inserido
            """,
            (email, nome),
        )
        row = cur.fetchone()
        conn.commit()
    return bool(row[0]) if row else False


def set_user_nivel_ativo(email: str, nivel: str, ativo: bool) -> bool:
    """
    Admin define nivel e status de um usuario. Ao DESATIVAR, revoga o token
    Bearer (api_token = NULL) na mesma operacao — credencial deixa de existir,
    nao so de funcionar. Retorna False se o usuario nao existir.
    """
    with _conn() as conn:
        if ativo:
            cur = conn.execute(
                "UPDATE notebooklm.users SET nivel = %s, ativo = true WHERE email = %s",
                (nivel, email),
            )
        else:
            cur = conn.execute(
                "UPDATE notebooklm.users SET nivel = %s, ativo = false, api_token = NULL "
                "WHERE email = %s",
                (nivel, email),
            )
        conn.commit()
        return cur.rowcount > 0


def issue_api_token(email: str) -> str | None:
    """
    Gera (rotaciona) o token Bearer por-usuario usado na API REST. Armazena
    apenas o HASH SHA-256 (nunca o token em claro) e retorna o token em claro
    UMA vez, para entrega. Retorna None se o usuario nao existir.
    """
    token = "nlm_" + secrets.token_urlsafe(32)
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE notebooklm.users SET api_token = %s WHERE email = %s",
            (_hash_token(token), email),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return token


def bootstrap_admin(email: str, nome: str) -> str:
    """
    Cria (ou promove) o email dado a admin ativo e emite um api_token novo.

    Autorizado no nivel do endpoint (POST /admin/bootstrap) pela posse de
    NOTEBOOKLM_BOOTSTRAP_KEY — um segredo de ambiente do servidor, nao uma
    identidade de usuario. Nao e "auto-promocao": quem tem essa chave ja tem o
    mesmo nivel de confianca de quem teria DATABASE_URL direto (poderia rodar
    este mesmo UPDATE via psql). Idempotente e sem limite de uso — nao so o
    primeiro admin, qualquer email autorizado por quem detem a chave.
    """
    token = "nlm_" + secrets.token_urlsafe(32)
    with _conn() as conn:
        conn.execute(
            """INSERT INTO notebooklm.users (email, nome, nivel, ativo, api_token)
               VALUES (%s, %s, 'admin', true, %s)
               ON CONFLICT (email) DO UPDATE SET
                   nome = EXCLUDED.nome, nivel = 'admin', ativo = true,
                   api_token = EXCLUDED.api_token""",
            (email, nome, _hash_token(token)),
        )
        conn.commit()
    return token


def get_user(email: str) -> dict | None:
    """Retorna dados do usuario ou None se nao existir."""
    with _conn() as conn:
        cur = conn.execute(
            "SELECT email, nome, nivel, ativo FROM notebooklm.users WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"email": row[0], "nome": row[1], "nivel": row[2], "ativo": row[3]}


def get_user_by_token(token: str) -> dict | None:
    """
    Identifica um usuario ATIVO pelo token Bearer, comparando pelo hash SHA-256
    (o banco guarda so o hash). O filtro `ativo = true` e feito no proprio SQL.
    """
    if not token:
        return None
    with _conn() as conn:
        cur = conn.execute(
            "SELECT email, nome, nivel, ativo FROM notebooklm.users "
            "WHERE api_token = %s AND ativo = true",
            (_hash_token(token),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"email": row[0], "nome": row[1], "nivel": row[2], "ativo": row[3]}


# Hierarquia de niveis. financeiro=1 e o piso por hierarquia, mas e nivel
# PARALELO nas consultas (gated por require_active_user + filtro de area), nao
# inferior — require_nivel so guarda operacoes admin/gestor.
HIERARQUIA = {"admin": 4, "gestor": 3, "juridico": 2, "financeiro": 1}


def nivel_atende(nivel: str | None, nivel_minimo: str) -> bool:
    """True se `nivel` satisfaz o minimo exigido (por hierarquia)."""
    return HIERARQUIA.get(nivel or "", 0) >= HIERARQUIA.get(nivel_minimo, 99)


def check_access(email: str, nivel_minimo: str) -> bool:
    """Verifica se o usuario (ativo) tem nivel suficiente."""
    user = get_user(email)
    if not user or not user["ativo"]:
        return False
    return nivel_atende(user["nivel"], nivel_minimo)


def check_active(email: str) -> bool:
    """
    Verifica apenas se o usuario esta cadastrado e ativo, sem hierarquia.
    Usado nas operacoes de consulta: financeiro e um nivel PARALELO (nao
    inferior) — quem decide o que cada um ve e o filtro por area (rpc).
    """
    user = get_user(email)
    return bool(user and user["ativo"])


# ── Audit log ─────────────────────────────────────────────────────────────────

def audit(email: str, notebook_id: str | None, pergunta: str, resposta: str = "",
          raise_on_error: bool = False, ip: str | None = None,
          session_account: str | None = None) -> None:
    """
    Registra acesso no audit_log. `pergunta` e `resposta` sao CIFRADAS com Fernet
    (como os tokens): conteudo juridico sigiloso nao fica legivel a quem tem
    apenas SELECT no banco. A trilha (quem/quando/qual notebook/IP/conta) permanece
    em claro para consulta; o teor exige a chave para decifrar.

    raise_on_error: se True, propaga a falha (fail-closed) em vez de so logar.
    Usado no caminho de consulta quando AUDIT_FAIL_CLOSED esta ligado, para
    garantir a exigencia LGPD de "toda pergunta gravada".
    """
    try:
        enc_pergunta = _fernet.encrypt((pergunta or "").encode()).decode()
        enc_resposta = _fernet.encrypt((resposta or "").encode()).decode()
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO notebooklm.audit_log
                    (email, notebook_id, pergunta, resposta, ip, session_account)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (email, notebook_id, enc_pergunta, enc_resposta, ip, session_account),
            )
            conn.commit()
    except Exception as e:
        logger.warning("Falha ao gravar audit_log: %s", e)
        if raise_on_error:
            raise


def log_access(evento: str, identity_email: str | None = None, *,
               session_account: str | None = None, ip: str | None = None,
               user_agent: str | None = None, notebook_id: str | None = None,
               resultado: str = "ok", detalhe: str | None = None) -> None:
    """
    Registra um evento de ACESSO no access_log (append-only). Base do painel de
    rastreamento e da correlacao IP x conta acessada x cadastro. Tolerante a
    falha: nunca derruba a operacao principal por causa do log.
    """
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO notebooklm.access_log
                    (evento, identity_email, session_account, ip, user_agent,
                     notebook_id, resultado, detalhe)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (evento, identity_email, session_account, ip, user_agent,
                 notebook_id, resultado, detalhe),
            )
            conn.commit()
    except Exception as e:
        logger.warning("Falha ao gravar access_log (%s): %s", evento, e)


# ── Notebooks ─────────────────────────────────────────────────────────────────

def list_team() -> list[dict]:
    """Lista todos os usuarios com status de token (para /team admin)."""
    with _conn() as conn:
        cur = conn.execute(
            """
            SELECT u.email, u.nome, u.nivel, u.ativo,
                   CASE WHEN t.email IS NOT NULL THEN true ELSE false END as tem_token,
                   t.atualizado_em
            FROM notebooklm.users u
            LEFT JOIN notebooklm.tokens t ON u.email = t.email
            ORDER BY u.nivel, u.nome
            """
        )
        rows = cur.fetchall()
    return [
        {
            "email": r[0], "nome": r[1], "nivel": r[2],
            "ativo": r[3], "tem_token": r[4],
            "token_atualizado": str(r[5]) if r[5] else None,
        }
        for r in rows
    ]


def get_allowed_notebooks(nivel: str) -> list[dict]:
    """Retorna notebooks que o nivel pode acessar."""
    NIVEIS_PERMITIDOS = {
        "admin":      ["juridico", "financeiro", "comercial"],
        "gestor":     ["juridico", "financeiro", "comercial"],
        "juridico":   ["juridico"],
        "financeiro": ["financeiro"],
    }
    areas = NIVEIS_PERMITIDOS.get(nivel, [])
    if not areas:
        return []
    with _conn() as conn:
        cur = conn.execute(
            "SELECT id, titulo, area FROM notebooklm.notebooks WHERE area = ANY(%s)",
            (areas,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "titulo": r[1], "area": r[2]} for r in rows]


# ── Compartilhamento (dono + shares; fonte de verdade do "de quem é") ────────────

def set_notebook_owner(notebook_id: str, owner_email: str) -> None:
    """Registra/atualiza o dono de um notebook."""
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO notebooklm.notebook_owners (notebook_id, owner_email, atualizado_em)
            VALUES (%s, %s, now())
            ON CONFLICT (notebook_id) DO UPDATE
              SET owner_email = EXCLUDED.owner_email, atualizado_em = now()
            """,
            (notebook_id, owner_email),
        )
        conn.commit()


def get_owners(ids: list[str]) -> dict[str, str]:
    """Mapa {notebook_id: owner_email} para os ids informados."""
    if not ids:
        return {}
    with _conn() as conn:
        cur = conn.execute(
            "SELECT notebook_id, owner_email FROM notebooklm.notebook_owners "
            "WHERE notebook_id = ANY(%s)",
            (ids,),
        )
        rows = cur.fetchall()
    return {r[0]: r[1] for r in rows}


def upsert_notebook_share(notebook_id: str, shared_with: str,
                          permission: str | None, view_level: str | None = None) -> None:
    """Registra/atualiza um compartilhamento (notebook -> usuario)."""
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO notebooklm.notebook_shares
                (notebook_id, shared_with, permission, view_level, atualizado_em)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (notebook_id, shared_with) DO UPDATE
              SET permission = EXCLUDED.permission,
                  view_level = COALESCE(EXCLUDED.view_level, notebooklm.notebook_shares.view_level),
                  atualizado_em = now()
            """,
            (notebook_id, shared_with, permission, view_level),
        )
        conn.commit()


def replace_notebook_shares(notebook_id: str, shares: list[tuple[str, str]]) -> None:
    """Substitui a lista de compartilhamentos de um notebook (usado no sync)."""
    with _conn() as conn:
        conn.execute(
            "DELETE FROM notebooklm.notebook_shares WHERE notebook_id = %s", (notebook_id,)
        )
        for email, permission in shares:
            conn.execute(
                """
                INSERT INTO notebooklm.notebook_shares
                    (notebook_id, shared_with, permission, atualizado_em)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (notebook_id, shared_with) DO UPDATE
                  SET permission = EXCLUDED.permission, atualizado_em = now()
                """,
                (notebook_id, email, permission),
            )
        conn.commit()


def upsert_notebooks(rows: list[dict]) -> int:
    """
    Insere/atualiza a classificacao de notebooks por area.
    rows: [{"id": ..., "titulo": ..., "area": "juridico|financeiro|comercial"}]
    Retorna a quantidade gravada.
    """
    validas = {"juridico", "financeiro", "comercial"}
    gravados = 0
    with _conn() as conn:
        for r in rows:
            if not r.get("id") or r.get("area") not in validas:
                continue
            conn.execute(
                """
                INSERT INTO notebooklm.notebooks (id, titulo, area)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET titulo = EXCLUDED.titulo, area = EXCLUDED.area
                """,
                (r["id"], r.get("titulo", ""), r["area"]),
            )
            gravados += 1
        conn.commit()
    return gravados
