"""
Tradução de exceção em resposta HTTP na REST.

Estes testes existem por causa de um defeito encontrado testando a instância
real: `GET /notebooks` com Bearer válido, de um usuário ativo mas sem sessão
Google no banco, devolvia **500 Internal Server Error**.

O `/auth/check` tratava o mesmo caso e respondia direito — a diferença passou
despercebida porque nenhum teste exercitava a tradução de exceção, e ler o
código não denuncia: o `raise` está em `db.py`, três camadas abaixo do endpoint.

O estado é comum, não exótico: qualquer pessoa ativada antes de rodar o
`connect.py`, ou cuja sessão foi removida, cai nele. "Internal Server Error" não
diz a ninguém o que fazer.
"""
import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture(scope="module")
def client():
    """
    Rotas sintéticas que levantam exatamente o que o código de produção levanta.

    Testar pelos endpoints reais exigiria banco e sessão Google. O que se quer
    provar aqui é só a tradução exceção -> HTTP, que é responsabilidade da app e
    independe de onde a exceção nasceu.
    """
    @api.app.get("/__teste_sem_sessao")
    async def _sem_sessao():
        # Mesma exceção e mensagem de db.get_storage_state()
        raise ValueError("Token nao encontrado para alguem@exemplo.com")

    @api.app.get("/__teste_sem_permissao")
    async def _sem_permissao():
        # Mesma exceção de rpc._check_notebook_access()
        raise PermissionError(
            "Notebook nao classificado para o seu nivel de acesso. "
            "Peca ao admin para classificar os notebooks por area."
        )

    return TestClient(api.app, raise_server_exceptions=False)


def test_sem_sessao_google_devolve_409_e_nao_500(client):
    """
    409, não 500: o servidor não falhou — falta um pré-requisito de estado.

    E não 401/403: a credencial está correta e o nível também. Tratar como falha
    de autenticação mandaria a pessoa procurar o problema no lugar errado.
    """
    r = client.get("/__teste_sem_sessao")
    assert r.status_code == 409, f"esperado 409, veio {r.status_code}"

    corpo = r.json()
    assert "Token nao encontrado" in corpo["detail"]
    assert "connect.py" in corpo["acao"], "a resposta precisa dizer o que fazer"


def test_fail_closed_devolve_403(client):
    """
    O caminho de negação por área não pode virar 500: a mensagem instrui a pedir
    a classificação ao admin, e só serve se chegar a quem chamou.
    """
    r = client.get("/__teste_sem_permissao")
    assert r.status_code == 403
    assert "classificar" in r.json()["detail"]


def test_openapi_nao_e_publico():
    """
    `docs_url=None` e `redoc_url=None` desligam só a UI. Sem `openapi_url=None` o
    schema completo — rotas, parâmetros, esquema de auth — fica servido sem
    autenticação nenhuma. Verificado num deploy real: /docs dava 404 e
    /openapi.json dava 200.
    """
    c = TestClient(api.app, raise_server_exceptions=False)
    for rota in ("/openapi.json", "/docs", "/redoc"):
        assert c.get(rota).status_code == 404, f"{rota} não deveria estar exposta"
