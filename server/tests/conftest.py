"""
Setup do ambiente de teste.

`config.py` le variaveis obrigatorias com `os.environ[...]` no import — e isso e
proposital (falhar no boot e melhor que subir apontando para o lugar errado).
Consequencia: o ambiente precisa existir ANTES de qualquer `import config`, o
que inclui o import indireto via `db`, `rpc` e `mcp_server`.

pytest importa conftest.py antes dos modulos de teste, entao este e o lugar.
Os valores sao descartaveis e nao tocam em nenhum servico real: DATABASE_URL
aponta para um host inexistente de proposito — se um teste vazar uma conexao de
verdade, ele falha em vez de escrever num banco.
"""
import os

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("NOTEBOOKLM_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost:1/test_nunca_conecta")
os.environ.setdefault("PUBLIC_URL", "https://test.invalid")

# Sem client id/secret o mcp_server nao monta o GoogleProvider — os testes de
# auth exercitam _dual_verify_token diretamente, entao precisamos dele montado.
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "000000000000-teste.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret-nao-e-real")

# Allowlist vazia por default: cada teste que precisa dela seta explicitamente.
os.environ.setdefault("NOTEBOOKLM_ALLOWED_DOMAINS", "")
os.environ.setdefault("NOTEBOOKLM_ALLOWED_EMAILS", "")


@pytest.fixture(autouse=True)
def _proibe_conexao_real(monkeypatch):
    """
    Rede de seguranca: nenhum teste pode abrir conexao de verdade com o Postgres.

    Sem isto, um mock aplicado no alvo errado nao falha — ele CAI NO CODIGO REAL
    e fica pendurado ate o timeout do psycopg. Foi o que aconteceu na primeira
    execucao desta suite: 4m23s de relogio, e o motivo real (patch no lugar
    errado) escondido atras de um "connection timeout expired".

    Aqui o mesmo erro vira falha instantanea, dizendo o que fazer.

    Nao da para resolver isso via `connect_timeout` na DATABASE_URL: o
    `_db_params()` do db.py remonta o dict de conexao a mao e descarta todos os
    parametros de query exceto `sslmode`.
    """
    import db

    def _bloqueia(*_a, **_kw):
        raise AssertionError(
            "Este teste tentou abrir uma conexao real com o Postgres. "
            "Algum @patch esta no alvo errado — verifique se o modulo sob teste "
            "importa a funcao no topo (patch em '<modulo>.<nome>') ou dentro do "
            "corpo (patch no modulo de origem)."
        )

    monkeypatch.setattr(db, "_conn", _bloqueia)
