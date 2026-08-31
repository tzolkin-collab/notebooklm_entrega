from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api
import db


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_BOOTSTRAP_KEY", "test-bootstrap-secret")
    api._rl_hits.clear()
    api.limiter.reset()
    return TestClient(api.app)


def test_bootstrap_disabled_without_key(client, monkeypatch):
    monkeypatch.delenv("NOTEBOOKLM_BOOTSTRAP_KEY")
    response = client.post("/admin/bootstrap", json={"email": "a@example.com"})
    assert response.status_code == 503


@pytest.mark.parametrize("key", [None, "wrong"])
def test_bootstrap_rejects_bad_key(client, key):
    headers = {"X-Bootstrap-Key": key} if key else {}
    response = client.post("/admin/bootstrap", json={"email": "a@example.com"}, headers=headers)
    assert response.status_code == 401


def test_bootstrap_rejects_invalid_email(client):
    response = client.post(
        "/admin/bootstrap",
        json={"email": "nao-e-email"},
        headers={"X-Bootstrap-Key": "test-bootstrap-secret"},
    )
    assert response.status_code == 400


def test_bootstrap_creates_admin(client, monkeypatch):
    create = MagicMock(return_value="nlm_plaintext-token")
    monkeypatch.setattr(db, "bootstrap_admin", create)
    response = client.post(
        "/admin/bootstrap",
        json={"email": "Doutor@Example.com", "nome": "Doutor"},
        headers={"X-Bootstrap-Key": "test-bootstrap-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["email"] == "doutor@example.com"
    assert body["nivel"] == "admin"
    assert body["api_token"] == "nlm_plaintext-token"
    create.assert_called_once_with("doutor@example.com", "Doutor")


def test_bootstrap_is_idempotent_for_multiple_emails(client, monkeypatch):
    create = MagicMock(return_value="nlm_plaintext-token")
    monkeypatch.setattr(db, "bootstrap_admin", create)
    log = MagicMock()
    monkeypatch.setattr(db, "log_access", log)

    r1 = client.post("/admin/bootstrap", json={"email": "a@example.com"},
                      headers={"X-Bootstrap-Key": "test-bootstrap-secret"})
    r2 = client.post("/admin/bootstrap", json={"email": "b@example.com"},
                      headers={"X-Bootstrap-Key": "test-bootstrap-secret"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert create.call_count == 2
    assert log.call_count == 2
    for call in log.call_args_list:
        assert call.args[0] == "bootstrap_admin"
        assert call.kwargs["resultado"] == "ok"


def mock_connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(db, "_conn", lambda: conn)
    return conn


def test_db_bootstrap_admin_upserts_and_returns_token(monkeypatch):
    conn = mock_connection(monkeypatch)
    token = db.bootstrap_admin("novo@example.com", "Novo")
    assert token.startswith("nlm_")
    assert conn.execute.call_count == 1
    query, params = conn.execute.call_args.args
    assert "ON CONFLICT (email) DO UPDATE" in query
    assert "nivel = 'admin'" in query
    assert params == ("novo@example.com", "Novo", db._hash_token(token))
    conn.commit.assert_called_once()
