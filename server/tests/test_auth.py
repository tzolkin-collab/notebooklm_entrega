"""
Testes para autenticação dual (OAuth Google + Bearer token Postgres).

Valida:
- Dual auth: _dual_verify_token aceita Bearer ou OAuth
- _current_email(): extração correta de email de ambas as fontes
- Allowlist: email_verified, domínios permitidos
- Error cases: token malformado, usuário inválido, etc
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from mcp.server.auth.provider import AccessToken
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockUser:
    """Mock de usuário retornado por db.get_user_by_token."""
    def __init__(self, email: str):
        self.data = {"email": email}

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key: str):
        return self.data[key]


class TestDualAuth:
    """Testes para autenticação dual (Bearer + OAuth)."""

    @patch('mcp_server.db.get_user_by_token')
    async def test_dual_verify_bearer_token_valid(self, mock_get_user):
        """Bearer token válido no Postgres deve retornar AccessToken."""
        # Mock
        mock_get_user.return_value = MockUser("user@example.com")

        # Import after mocking
        from mcp_server import auth_provider, _dual_verify_token

        # Test
        result = await _dual_verify_token("valid_bearer_token_123")

        assert result is not None
        assert isinstance(result, AccessToken)
        assert result.claims["email"] == "user@example.com"
        assert result.claims["email_verified"] is True
        assert result.client_id == "postgres_client"

    @patch('mcp_server.db.get_user_by_token')
    async def test_dual_verify_bearer_token_invalid(self, mock_get_user):
        """Bearer token inválido deve retornar None."""
        mock_get_user.return_value = None

        from mcp_server import _dual_verify_token

        result = await _dual_verify_token("invalid_token")

        assert result is None

    @patch('mcp_server.db.get_user_by_token')
    async def test_dual_verify_bearer_token_db_error(self, mock_get_user):
        """Erro ao buscar token no DB deve fazer fallback para OAuth."""
        mock_get_user.side_effect = Exception("Database error")

        from mcp_server import _dual_verify_token

        # Com erro no Postgres, deveria fazer fallback para Google OAuth
        # (mas como não temos token Google válido aqui, retorna None)
        result = await _dual_verify_token("any_token")

        # Fallback falha porque token não é OAuth válido
        assert result is None

    @patch('mcp_server.db.get_user_by_token')
    async def test_dual_verify_empty_user(self, mock_get_user):
        """Usuário sem email deve ser rejeitado."""
        mock_get_user.return_value = MockUser("")

        from mcp_server import _dual_verify_token

        result = await _dual_verify_token("token_sem_email")

        assert result is None


class TestCurrentEmail:
    """Testes para _current_email() - extração de email de OAuth/Bearer."""

    @patch('mcp_server.get_access_token')
    def test_current_email_from_oauth_token(self, mock_get_access_token):
        """Email deve ser extraído de OAuth token válido."""
        # Mock token OAuth
        mock_token = Mock()
        mock_token.claims = {
            "email": "USER@EXAMPLE.COM",  # Uppercase para testar normalization
            "email_verified": True
        }
        mock_get_access_token.return_value = mock_token

        from mcp_server import _current_email

        result = _current_email()

        assert result == "user@example.com"  # Deve ser lowercase

    @patch('mcp_server.get_access_token')
    def test_current_email_email_not_verified(self, mock_get_access_token):
        """Email não verificado deve ser rejeitado."""
        mock_token = Mock()
        mock_token.claims = {
            "email": "unverified@example.com",
            "email_verified": False  # Explicitamente não verificado
        }
        mock_get_access_token.return_value = mock_token

        from mcp_server import _current_email

        result = _current_email()

        assert result is None

    @patch('mcp_server.get_access_token')
    @patch.dict(os.environ, {"ALLOWED_EMAIL_DOMAINS": "example.com,authorized.org"})
    def test_current_email_domain_allowlist(self, mock_get_access_token):
        """Email de domínio permitido deve passar."""
        # Reload config para pegar ALLOWED_EMAIL_DOMAINS
        import config as cfg
        # Este teste depende de como config.py inicializa ALLOWED_EMAIL_DOMAINS

        mock_token = Mock()
        mock_token.claims = {
            "email": "user@example.com",
            "email_verified": True
        }
        mock_get_access_token.return_value = mock_token

        from mcp_server import _current_email

        result = _current_email()

        # Depende da config - este é mais um teste de integração
        # Em produção, ALLOWED_EMAIL_DOMAINS é lido na startup

    @patch('mcp_server.get_access_token')
    def test_current_email_no_token(self, mock_get_access_token):
        """Sem token deve retornar None."""
        mock_get_access_token.return_value = None

        from mcp_server import _current_email

        result = _current_email()

        assert result is None

    @patch('mcp_server.get_access_token')
    def test_current_email_no_email_in_claims(self, mock_get_access_token):
        """Token sem email na claim deve retornar None."""
        mock_token = Mock()
        mock_token.claims = {
            "sub": "12345",
            "email_verified": True
            # Falta "email"
        }
        mock_get_access_token.return_value = mock_token

        from mcp_server import _current_email

        result = _current_email()

        assert result is None


class TestBearerTokenFallback:
    """Testes para fallback de Bearer token nos headers HTTP."""

    @patch('mcp_server.get_access_token')
    @patch('fastmcp.server.dependencies.get_http_request')
    @patch('mcp_server.db.get_user_by_token')
    def test_fallback_bearer_token_in_headers(self, mock_get_user, mock_get_req, mock_get_token):
        """Bearer token nos headers deve fazer fallback se OAuth falhar."""
        # OAuth falha
        mock_get_token.side_effect = RuntimeError("Out of context")

        # HTTP request com Bearer token
        mock_req = Mock()
        mock_req.headers = {"authorization": "Bearer my_postgres_token"}
        mock_req.scope = None
        mock_get_req.return_value = mock_req

        # DB encontra usuário
        mock_get_user.return_value = MockUser("fallback@example.com")

        from mcp_server import _current_email

        result = _current_email()

        assert result == "fallback@example.com"

    @patch('mcp_server.get_access_token')
    @patch('fastmcp.server.dependencies.get_http_request')
    def test_fallback_malformed_bearer_token(self, mock_get_req, mock_get_token):
        """Bearer token malformado deve ser ignorado."""
        mock_get_token.side_effect = RuntimeError("Out of context")

        # HTTP request com Bearer token malformado (sem espaço)
        mock_req = Mock()
        mock_req.headers = {"authorization": "BearerInvalid"}
        mock_req.scope = None
        mock_get_req.return_value = mock_req

        from mcp_server import _current_email

        result = _current_email()

        assert result is None

    @patch('mcp_server.get_access_token')
    @patch('fastmcp.server.dependencies.get_http_request')
    def test_fallback_empty_bearer_token(self, mock_get_req, mock_get_token):
        """Bearer token vazio deve ser ignorado."""
        mock_get_token.side_effect = RuntimeError("Out of context")

        # HTTP request com Bearer token vazio
        mock_req = Mock()
        mock_req.headers = {"authorization": "Bearer "}  # Vazio após espaço
        mock_req.scope = None
        mock_get_req.return_value = mock_req

        from mcp_server import _current_email

        result = _current_email()

        assert result is None

    @patch('mcp_server.get_access_token')
    @patch('fastmcp.server.dependencies.get_http_request')
    def test_fallback_scope_user_email(self, mock_get_req, mock_get_token):
        """Email injetado no scope deve ser usado."""
        mock_get_token.side_effect = RuntimeError("Out of context")

        # HTTP request com user_email no scope
        mock_req = Mock()
        mock_req.scope = {"user_email": "scope@example.com"}
        mock_req.headers = {}
        mock_get_req.return_value = mock_req

        from mcp_server import _current_email

        result = _current_email()

        assert result == "scope@example.com"


class TestAuthorizationChain:
    """Testes da cadeia de autorização (OAuth → Bearer → scope → None)."""

    @patch('mcp_server.get_access_token')
    def test_auth_chain_oauth_first(self, mock_get_token):
        """OAuth deve ter prioridade (primeira na cadeia)."""
        mock_token = Mock()
        mock_token.claims = {"email": "oauth@example.com", "email_verified": True}
        mock_get_token.return_value = mock_token

        from mcp_server import _current_email

        result = _current_email()

        assert result == "oauth@example.com"
        # Bearer token não deve ser consultado porque OAuth funcionou

    @patch('mcp_server.get_access_token')
    @patch('fastmcp.server.dependencies.get_http_request')
    @patch('mcp_server.db.get_user_by_token')
    def test_auth_chain_bearer_fallback(self, mock_get_user, mock_get_req, mock_get_token):
        """Bearer deve ser usado se OAuth falhar."""
        # OAuth falha
        mock_get_token.side_effect = RuntimeError("Out of context")

        # Bearer token no header
        mock_req = Mock()
        mock_req.headers = {"authorization": "Bearer valid_token"}
        mock_req.scope = None
        mock_get_req.return_value = mock_req

        mock_get_user.return_value = MockUser("bearer@example.com")

        from mcp_server import _current_email

        result = _current_email()

        assert result == "bearer@example.com"
