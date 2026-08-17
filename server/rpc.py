"""
Chamadas ao NotebookLM — usa o token do usuario buscado no Postgres.
"""
import logging
from auth import get_client_for
from config import AUDIT_FAIL_CLOSED
import db

# Enums de compartilhamento (notebooklm-py 0.6.0). Import defensivo: preferir o
# path publico, cair para o interno se necessario.
try:
    from notebooklm import SharePermission, ShareViewLevel
except Exception:  # pragma: no cover
    from notebooklm.rpc.types import SharePermission, ShareViewLevel

logger = logging.getLogger(__name__)

_PERM = {"viewer": SharePermission.VIEWER, "editor": SharePermission.EDITOR}
_VIEW = {"completo": ShareViewLevel.FULL_NOTEBOOK, "chat": ShareViewLevel.CHAT_ONLY}


async def list_notebooks(email: str) -> list[dict]:
    async with get_client_for(email) as client:
        notebooks = await client.notebooks.list()
        user = db.get_user(email)
        nivel = user["nivel"] if user else None
        allowed = {n["id"] for n in db.get_allowed_notebooks(nivel)} if user else set()
        if not allowed:
            # Fail-closed: sem classificacao na tabela notebooklm.notebooks,
            # so admin/gestor (que podem ver todas as areas) recebem a lista
            # completa. Demais niveis recebem vazio ate o admin classificar
            # os notebooks por area — inconveniencia em vez de vazamento.
            if nivel not in ("admin", "gestor"):
                logger.warning(
                    "tabela notebooks sem entradas para nivel=%s (email=%s) — "
                    "retornando lista vazia (fail-closed)", nivel, email,
                )
                return []
            return [
                {"id": nb.id, "title": nb.title, "created_at": str(nb.created_at)}
                for nb in notebooks
            ]
        return [
            {"id": nb.id, "title": nb.title, "created_at": str(nb.created_at)}
            for nb in notebooks
            if nb.id in allowed
        ]


def _check_notebook_access(email: str, notebook_id: str) -> None:
    """
    Aplica o filtro por area tambem no acesso direto por ID (fail-closed).
    admin/gestor acessam qualquer notebook; demais niveis so os classificados
    para a sua area na tabela notebooklm.notebooks.
    """
    user = db.get_user(email)
    nivel = user["nivel"] if user else None
    if nivel in ("admin", "gestor"):
        return
    allowed = {n["id"] for n in db.get_allowed_notebooks(nivel)} if user else set()
    if notebook_id not in allowed:
        logger.warning(
            "acesso negado a notebook %s para nivel=%s (email=%s) — "
            "sem classificacao de area (fail-closed)", notebook_id, nivel, email,
        )
        raise PermissionError(
            "Notebook nao classificado para o seu nivel de acesso. "
            "Peca ao admin para classificar os notebooks por area."
        )


async def ask(email: str, notebook_id: str, question: str,
              source_ids: list[str] | None = None, ip: str | None = None) -> dict:
    _check_notebook_access(email, notebook_id)
    async with get_client_for(email) as client:
        result = await client.chat.ask(notebook_id, question, source_ids=source_ids)
        answer = {
            "answer": result.answer,
            "conversation_id": result.conversation_id,
            "references": [
                {
                    "citation_number": ref.citation_number,
                    "source_id": ref.source_id,
                    "cited_text": getattr(ref, "cited_text", None),
                }
                for ref in (result.references or [])
            ],
        }
    # Guarda pergunta e resposta COMPLETAS (cifradas) + correlacao IP/conta, para
    # a visao "usos e dados de cada requisicao" do painel.
    db.audit(email, notebook_id, question, result.answer,
             raise_on_error=AUDIT_FAIL_CLOSED, ip=ip,
             session_account=db.get_google_account(email))
    return answer


async def add_source_url(email: str, notebook_id: str, url: str) -> dict:
    _check_notebook_access(email, notebook_id)
    async with get_client_for(email) as client:
        source = await client.sources.add_url(notebook_id, url)
        return {"id": source.id, "title": source.title, "type": str(source.type)}


async def list_sources(email: str, notebook_id: str) -> list[dict]:
    _check_notebook_access(email, notebook_id)
    async with get_client_for(email) as client:
        sources = await client.sources.list(notebook_id)
        return [
            {
                "id": s.id,
                "title": s.title,
                "url": s.url,
                "kind": str(s.kind) if hasattr(s, "kind") else None,
                "status": str(s.status),
            }
            for s in sources
        ]


async def add_source_drive(
    email: str,
    notebook_id: str,
    file_id: str,
    title: str,
    mime_type: str = "application/vnd.google-apps.document",
) -> dict:
    _check_notebook_access(email, notebook_id)
    async with get_client_for(email) as client:
        source = await client.sources.add_drive(notebook_id, file_id, title, mime_type=mime_type)
        return {"id": source.id, "title": source.title, "type": str(source.type)}


async def create_notebook(email: str, title: str) -> dict:
    async with get_client_for(email) as client:
        nb = await client.notebooks.create(title)
        return {"id": nb.id, "title": nb.title}


# ── Compartilhamento e visibilidade ──────────────────────────────────────────────

async def list_shared(email: str) -> list[dict]:
    """
    Lista os notebooks que o usuario acessa, marcando `meu` vs `compartilhado`
    (via Notebook.is_owner do 0.6.0) e resolvendo o DONO a partir dos nossos
    registros (notebook_owners) — ja que a lib nao expoe o email do dono.
    Aplica o mesmo filtro por area do list_notebooks (fail-closed).
    """
    user = db.get_user(email)
    nivel = user["nivel"] if user else None
    privilegiado = nivel in ("admin", "gestor")
    async with get_client_for(email) as client:
        notebooks = await client.notebooks.list()

    allowed = {n["id"] for n in db.get_allowed_notebooks(nivel)} if user else set()
    if not privilegiado and not allowed:
        # fail-closed: nivel sem classificacao nao ve nada (inconveniencia > vazamento)
        return []

    owners = db.get_owners([nb.id for nb in notebooks])
    out = []
    for nb in notebooks:
        if not privilegiado and nb.id not in allowed:
            continue
        dono = owners.get(nb.id) or (email if nb.is_owner else "não registrado")
        out.append({
            "id": nb.id,
            "title": nb.title,
            "papel": "meu" if nb.is_owner else "compartilhado",
            "dono": dono,
            "sources_count": nb.sources_count,
            "created_at": str(nb.created_at) if nb.created_at else None,
        })
    return out


def _shared_users_payload(status) -> list[dict]:
    return [
        {"email": u.email, "permissao": u.permission.name.lower(), "nome": u.display_name}
        for u in status.shared_users
    ]


async def share_notebook(admin_email: str, notebook_id: str, target_email: str,
                         permission: str = "viewer", notify: bool = True,
                         view_level: str | None = None) -> dict:
    """Compartilha um notebook (roda sob a sessao do admin/dono) e grava na nossa
    fonte de verdade. `view_level` (opcional) afeta o notebook TODO."""
    perm = _PERM.get((permission or "").lower(), SharePermission.VIEWER)
    async with get_client_for(admin_email) as client:
        status = await client.sharing.add_user(notebook_id, target_email, perm, notify=notify)
        if view_level:
            lvl = _VIEW.get(view_level.lower())
            if lvl is not None:
                status = await client.sharing.set_view_level(notebook_id, lvl)
    db.set_notebook_owner(notebook_id, admin_email)
    db.upsert_notebook_share(notebook_id, target_email, perm.name.lower(),
                             (view_level or None))
    return {
        "ok": True,
        "notebook_id": notebook_id,
        "compartilhado_com": target_email,
        "permissao": perm.name.lower(),
        "quem_ve": _shared_users_payload(status),
    }


async def share_status(email: str, notebook_id: str) -> dict:
    """Mostra com quem um notebook esta compartilhado (get_status — lado dono)."""
    async with get_client_for(email) as client:
        st = await client.sharing.get_status(notebook_id)
    # Espelha na nossa base para o painel.
    db.replace_notebook_shares(
        notebook_id, [(u.email, u.permission.name.lower()) for u in st.shared_users]
    )
    return {
        "notebook_id": notebook_id,
        "publico": st.is_public,
        "link": st.share_url,
        "quem_ve": _shared_users_payload(st),
    }


async def sync_shares(admin_email: str, limite: int | None = None) -> dict:
    """Enumera os notebooks do admin, registra o dono e reconstroi 'quem ve cada
    um' (get_status) na nossa base. Alimenta o painel. Pode ser lento (1 chamada
    por notebook) — use `limite` para testar."""
    n_shares = 0
    async with get_client_for(admin_email) as client:
        notebooks = await client.notebooks.list()
        owned = [nb for nb in notebooks if nb.is_owner]
        if limite:
            owned = owned[:limite]
        for nb in owned:
            db.set_notebook_owner(nb.id, admin_email)
            try:
                st = await client.sharing.get_status(nb.id)
                db.replace_notebook_shares(
                    nb.id, [(u.email, u.permission.name.lower()) for u in st.shared_users]
                )
                n_shares += len(st.shared_users)
            except Exception as e:
                logger.warning("sync_shares: get_status falhou p/ %s: %s", nb.id, e)
    return {"ok": True, "notebooks_dono": len(owned), "shares_registrados": n_shares}
