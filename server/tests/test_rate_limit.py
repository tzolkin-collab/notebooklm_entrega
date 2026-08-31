"""
Teto global de requisições, aplicado antes da autenticação.

Existe por causa de um furo verificado contra o deploy real: 13 requisições sem
credencial em `/api/auth/check` não produziram nenhum `429`. O `@limiter.limit()`
do slowapi decora a função da rota, mas o FastAPI resolve as dependências antes
de chamá-la — nos endpoints com `Depends(auth)`, o `401` acontece antes de o
contador existir.

A correção óbvia não funciona, e isso também está coberto aqui: o
`SlowAPIMiddleware` tem, no `_should_exempt`,

    # there is a decorator for this route we let the decorator handle it
    if name in limiter._route_limits: return True

ou seja, ele pula justamente as rotas decoradas. Adicioná-lo não muda nada.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_com_teto(monkeypatch):
    """Recarrega o módulo com um teto baixo — 120/min levaria minutos para testar."""
    monkeypatch.setenv("NOTEBOOKLM_RATE_GLOBAL_POR_MIN", "3")
    import api
    importlib.reload(api)
    yield api
    monkeypatch.delenv("NOTEBOOKLM_RATE_GLOBAL_POR_MIN", raising=False)
    importlib.reload(api)


def test_limita_requisicao_sem_credencial(app_com_teto):
    """
    O ponto todo: sem autenticação, o contador precisa rodar mesmo assim.

    Não é sobre adivinhar token — 32 bytes aleatórios tornam isso inviável. É
    sobre carga: cada tentativa custa um SHA-256 e uma consulta ao Postgres.
    """
    c = TestClient(app_com_teto.app, raise_server_exceptions=False)
    codigos = [c.get("/auth/check").status_code for _ in range(6)]

    assert codigos[:3] == [401, 401, 401], f"as 3 primeiras deviam passar: {codigos}"
    assert codigos[3] == 429, f"a 4ª devia ser barrada com teto=3: {codigos}"
    assert 429 in codigos[4:], "o bloqueio precisa persistir na janela"


def test_mensagem_do_429_diz_o_limite(app_com_teto):
    c = TestClient(app_com_teto.app, raise_server_exceptions=False)
    for _ in range(4):
        r = c.get("/auth/check")
    assert r.status_code == 429
    assert "3" in r.json()["detail"], "a mensagem deve informar o limite aplicado"


def test_health_nunca_e_limitado(app_com_teto):
    """
    O `HEALTHCHECK` do container bate em /health a cada 30s. Limitar o próprio
    healthcheck faria o container ser marcado unhealthy e reiniciar sob carga —
    transformando excesso de tráfego em queda de serviço, que é o oposto do que
    um rate limit existe para fazer.
    """
    c = TestClient(app_com_teto.app, raise_server_exceptions=False)
    codigos = [c.get("/health").status_code for _ in range(10)]
    assert set(codigos) == {200}, f"/health não pode ser barrado: {codigos}"


def test_contagem_e_por_ip(app_com_teto):
    """
    Um cliente abusivo não pode derrubar os outros.

    Ressalva de produção: isso só é verdade se o uvicorn enxergar o IP real. Com
    `FORWARDED_ALLOW_IPS` sem o IP do proxy, toda a internet chega como o IP do
    proxy e passa a dividir um balde só. Ver docs/VERIFICACAO.md.
    """
    api = app_com_teto
    api._rl_hits.clear()

    c1 = TestClient(api.app, raise_server_exceptions=False, client=("10.0.0.1", 1))
    c2 = TestClient(api.app, raise_server_exceptions=False, client=("10.0.0.2", 1))

    for _ in range(4):
        c1.get("/auth/check")
    assert c1.get("/auth/check").status_code == 429, "o primeiro IP devia estar barrado"
    assert c2.get("/auth/check").status_code == 401, "o segundo IP não pode ser afetado"
