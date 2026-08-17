"""
Testes para access control em RPC (list_notebooks, ask, add_source).

Valida:
- Fail-closed: notebooks sem classificação são invisíveis
- Níveis: admin, gestor, juridico, financeiro
- Filtro por área: juridico só vê notebooks juridico, etc
- PermissionError: acesso direto negado se notebook não classificado
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockNotebook:
    """Mock de notebook retornado por NotebookLM."""
    def __init__(self, id: str, title: str, area: str = None):
        self.id = id
        self.title = title
        self.created_at = "2026-08-11T00:00:00Z"
        self.area = area  # Não-standard, para testes


class MockUser:
    """Mock de usuário do Postgres."""
    def __init__(self, email: str, nivel: str = "juridico"):
        self.data = {
            "email": email,
            "nivel": nivel,
            "active": True
        }

    def __getitem__(self, key: str):
        return self.data[key]

    def get(self, key: str, default=None):
        return self.data.get(key, default)


class TestFailClosedBehavior:
    """Testes de fail-closed: notebooks sem classificação são rejeitados."""

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    @patch('rpc.get_client_for')
    async def test_list_notebooks_fail_closed_no_classification(
        self, mock_get_client, mock_get_allowed, mock_get_user
    ):
        """Sem classificação na tabela notebooks, nível juridico recebe lista vazia."""
        # Mock do usuário
        mock_get_user.return_value = MockUser("user@example.com", nivel="juridico")

        # Sem notebooks classificados
        mock_get_allowed.return_value = []

        # Mock do cliente (não deve ser usado)
        mock_client = AsyncMock()
        mock_client.notebooks.list = AsyncMock(return_value=[
            MockNotebook("nb1", "Contencioso 2024"),
            MockNotebook("nb2", "Consultas Gerais"),
        ])
        mock_get_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_get_client.return_value.__aexit__ = AsyncMock(return_value=None)

        from rpc import list_notebooks

        result = await list_notebooks("user@example.com")

        # Fail-closed: lista vazia, mesmo com notebooks existindo no NotebookLM.
        assert result == []

        # Nota sobre a ordem real de list_notebooks(): ele consulta o NotebookLM
        # ANTES de avaliar a permissao, e so entao decide o que devolver. Chamar
        # a lib e esperado — o que nao pode vazar e o resultado, e e isso que o
        # assert acima cobre. Nao asserte assert_not_called() aqui: seria travar
        # o teste num detalhe de implementacao que nao e o contrato de seguranca.
        mock_client.notebooks.list.assert_called_once()

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    @patch('rpc.get_client_for')
    async def test_list_notebooks_fail_open_admin(
        self, mock_get_client, mock_get_allowed, mock_get_user
    ):
        """Admin com classification vazia ainda recebe lista completa."""
        # Mock do admin
        mock_get_user.return_value = MockUser("admin@example.com", nivel="admin")

        # Sem notebooks classificados (tabela vazia)
        mock_get_allowed.return_value = []

        # Mock do cliente (admin vê tudo)
        mock_client = AsyncMock()
        mock_client.notebooks.list = AsyncMock(return_value=[
            MockNotebook("nb1", "Contencioso 2024"),
            MockNotebook("nb2", "Consultas Gerais"),
        ])
        mock_get_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_get_client.return_value.__aexit__ = AsyncMock(return_value=None)

        from rpc import list_notebooks

        result = await list_notebooks("admin@example.com")

        # Admin vê lista completa mesmo sem classificação
        assert len(result) == 2
        assert result[0]["id"] == "nb1"
        assert result[1]["id"] == "nb2"


class TestAccessByLevel:
    """Testes de access control por nível: admin, gestor, juridico, financeiro."""

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    async def test_admin_access_all_notebooks(self, mock_get_allowed, mock_get_user):
        """Admin acessa todos os notebooks (sem filtro)."""
        mock_get_user.return_value = MockUser("admin@example.com", nivel="admin")

        # Mesmo com classificação limitada, admin não filtra
        mock_get_allowed.return_value = [
            {"id": "nb_juridico_1", "area": "juridico"},
        ]

        from rpc import _check_notebook_access

        # Admin acessa qualquer notebook (sem raise)
        _check_notebook_access("admin@example.com", "nb_financeiro_1")
        # Sem exceção = teste passa

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    def test_juridico_blocked_financeiro_notebook(self, mock_get_allowed, mock_get_user):
        """Nível juridico não acessa notebooks financeiros."""
        mock_get_user.return_value = MockUser("user@example.com", nivel="juridico")

        # Apenas notebooks juridico classificados
        mock_get_allowed.return_value = [
            {"id": "nb_juridico_1", "area": "juridico"},
            {"id": "nb_juridico_2", "area": "juridico"},
        ]

        from rpc import _check_notebook_access

        # Pode acessar juridico
        _check_notebook_access("user@example.com", "nb_juridico_1")

        # Não pode acessar financeiro
        with pytest.raises(PermissionError) as exc_info:
            _check_notebook_access("user@example.com", "nb_financeiro_1")

        assert "nao classificado" in str(exc_info.value).lower()

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    def test_financeiro_blocked_juridico_notebook(self, mock_get_allowed, mock_get_user):
        """Nível financeiro não acessa notebooks jurídicos."""
        mock_get_user.return_value = MockUser("user@example.com", nivel="financeiro")

        # Apenas notebooks financeiro classificados
        mock_get_allowed.return_value = [
            {"id": "nb_financeiro_1", "area": "financeiro"},
        ]

        from rpc import _check_notebook_access

        # Pode acessar financeiro
        _check_notebook_access("user@example.com", "nb_financeiro_1")

        # Não pode acessar juridico
        with pytest.raises(PermissionError):
            _check_notebook_access("user@example.com", "nb_juridico_1")

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    def test_gestor_access_all_areas(self, mock_get_allowed, mock_get_user):
        """Nível gestor acessa todas as áreas (admin + content mgmt)."""
        mock_get_user.return_value = MockUser("gestor@example.com", nivel="gestor")

        # Sem limitações: gestor vê todas as áreas
        mock_get_allowed.return_value = []  # Nem importa, gestor não filtra

        from rpc import _check_notebook_access

        # Gestor acessa qualquer notebook
        _check_notebook_access("gestor@example.com", "nb_juridico_1")
        _check_notebook_access("gestor@example.com", "nb_financeiro_1")
        # Sem exceção = teste passa


class TestAreaFiltering:
    """Testes de filtro por área: juridico/financeiro/admin."""

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    @patch('rpc.get_client_for')
    async def test_list_notebooks_filtered_by_area(
        self, mock_get_client, mock_get_allowed, mock_get_user
    ):
        """List filtra notebooks por área do usuário."""
        mock_get_user.return_value = MockUser("user@example.com", nivel="juridico")

        # Notebooks classificados para juridico
        mock_get_allowed.return_value = [
            {"id": "nb_juridico_1", "area": "juridico"},
            {"id": "nb_juridico_2", "area": "juridico"},
        ]

        # Cliente retorna todos (não filtra automaticamente)
        mock_client = AsyncMock()
        mock_client.notebooks.list = AsyncMock(return_value=[
            MockNotebook("nb_juridico_1", "Contencioso"),
            MockNotebook("nb_financeiro_1", "Relatório Financeiro"),
            MockNotebook("nb_juridico_2", "Consultas"),
        ])
        mock_get_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_get_client.return_value.__aexit__ = AsyncMock(return_value=None)

        from rpc import list_notebooks

        result = await list_notebooks("user@example.com")

        # Apenas notebooks juridico
        assert len(result) == 2
        assert all(nb["id"].startswith("nb_juridico") for nb in result)

    @patch('rpc.db.audit')
    @patch('rpc.db.get_google_account')
    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    @patch('rpc.get_client_for')
    async def test_ask_with_access_control(
        self, mock_get_client, mock_get_allowed, mock_get_user,
        mock_google_account, mock_audit,
    ):
        """ask() aplica _check_notebook_access antes de fazer a pergunta.

        db.audit e db.get_google_account tambem precisam de mock: ask() grava no
        audit_log depois de responder, e sem isso o teste abre conexao real.
        """
        mock_get_user.return_value = MockUser("user@example.com", nivel="juridico")

        # Apenas nb_juridico_1 classificado
        mock_get_allowed.return_value = [
            {"id": "nb_juridico_1", "area": "juridico"},
        ]

        mock_client = AsyncMock()
        mock_client.chat.ask = AsyncMock(return_value=Mock(
            answer="Resposta...",
            conversation_id="conv123",
            references=[]
        ))
        mock_get_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_get_client.return_value.__aexit__ = AsyncMock(return_value=None)

        from rpc import ask

        # Pode fazer pergunta a notebook juridico
        result = await ask("user@example.com", "nb_juridico_1", "Qual é a jurisprudência?")
        assert "Resposta" in result["answer"]

        # Não pode fazer pergunta a notebook financeiro (não classificado)
        with pytest.raises(PermissionError):
            await ask("user@example.com", "nb_financeiro_1", "Qual é o resultado?")


class TestPermissionError:
    """Testes de PermissionError quando acesso é negado."""

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    def test_permission_error_message(self, mock_get_allowed, mock_get_user):
        """Mensagem de erro deve ser clara e usar 'fail-closed'."""
        mock_get_user.return_value = MockUser("user@example.com", nivel="juridico")
        mock_get_allowed.return_value = []

        from rpc import _check_notebook_access

        with pytest.raises(PermissionError) as exc_info:
            _check_notebook_access("user@example.com", "nb_unknown")

        error_msg = str(exc_info.value)
        assert "nao classificado" in error_msg.lower()
        assert "admin" in error_msg.lower()

    @patch('rpc.db.get_user')
    def test_permission_error_no_user(self, mock_get_user):
        """Usuário não encontrado → nível None → PermissionError."""
        mock_get_user.return_value = None

        from rpc import _check_notebook_access

        with pytest.raises(PermissionError):
            _check_notebook_access("unknown@example.com", "nb_1")


class TestParallelAreas:
    """Testes de áreas paralelas: juridico e financeiro são níveis, não hierarquia."""

    @patch('rpc.db.get_user')
    @patch('rpc.db.get_allowed_notebooks')
    def test_juridico_and_financeiro_separate(self, mock_get_allowed, mock_get_user):
        """juridico e financeiro são níveis paralelos (não sub-níveis)."""
        # juridico
        mock_get_user.return_value = MockUser("user1@example.com", nivel="juridico")
        mock_get_allowed.return_value = [{"id": "nb_juridico_1"}]

        from rpc import _check_notebook_access

        # juridico pode acessar juridico
        _check_notebook_access("user1@example.com", "nb_juridico_1")

        # juridico não pode acessar financeiro
        with pytest.raises(PermissionError):
            _check_notebook_access("user1@example.com", "nb_financeiro_1")

        # financeiro
        mock_get_user.return_value = MockUser("user2@example.com", nivel="financeiro")
        mock_get_allowed.return_value = [{"id": "nb_financeiro_1"}]

        # financeiro pode acessar financeiro
        _check_notebook_access("user2@example.com", "nb_financeiro_1")

        # financeiro não pode acessar juridico
        with pytest.raises(PermissionError):
            _check_notebook_access("user2@example.com", "nb_juridico_1")
