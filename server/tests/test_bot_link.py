import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api
import bot_link
import db
import mcp_server


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_BOT_CALLBACK_KEY", "test-bot-secret")
    api._rl_hits.clear()
    api.limiter.reset()
    return TestClient(api.app)


@pytest.fixture
def payload():
    return {
        "link_token": "link_" + "a" * 43,
        "google_account": "Person@Example.com",
        "storage_state": {"cookies": [
            {"name": "SID", "value": "private-cookie", "domain": ".google.com", "path": "/"}
        ], "origins": []},
    }


def test_callback_disabled(client, monkeypatch, payload):
    monkeypatch.delenv("NOTEBOOKLM_BOT_CALLBACK_KEY")
    assert client.post("/bot/token", json=payload).status_code == 503


@pytest.mark.parametrize("key", [None, "wrong"])
def test_callback_rejects_unauthenticated(client, payload, key):
    headers = {"X-Bot-Key": key} if key else {}
    assert client.post("/bot/token", json=payload, headers=headers).status_code == 401


def test_callback_binds_using_code(client, monkeypatch, payload):
    save = MagicMock(return_value="person@example.com")
    monkeypatch.setattr(db, "save_bot_storage_state", save)
    response = client.post("/bot/token", json=payload, headers={"X-Bot-Key": "test-bot-secret"})
    assert response.json() == {"status": "ok", "email": "person@example.com"}
    save.assert_called_once_with(payload["link_token"], payload["storage_state"], "person@example.com")
    assert "private-cookie" not in response.text


@pytest.mark.parametrize("change", [
    {"email": "victim@example.com"},
    {"nivel": "admin"},
    {"storage_state": {"cookies": [None]}},
    {"storage_state": {"cookies": "invalid"}},
    {"storage_state": {"cookies": [{"name": "SID", "value": "secret", "domain": "evilgoogle.com", "path": "/"}]}},
    {"link_token": "invalid"},
    {"google_account": None},
])
def test_invalid_payload_does_not_consume(client, monkeypatch, payload, change):
    save = MagicMock()
    monkeypatch.setattr(db, "save_bot_storage_state", save)
    response = client.post("/bot/token", json=payload | change, headers={"X-Bot-Key": "test-bot-secret"})
    assert response.status_code == 400
    save.assert_not_called()
    assert "private-cookie" not in response.text


def test_replay_expired_inactive_or_wrong_account(client, monkeypatch, payload):
    monkeypatch.setattr(db, "save_bot_storage_state", MagicMock(return_value=None))
    assert client.post("/bot/token", json=payload, headers={"X-Bot-Key": "test-bot-secret"}).status_code == 403


def test_size_limit_and_malformed_json(client):
    headers = {"X-Bot-Key": "test-bot-secret"}
    assert client.post("/bot/token", content=b"x" * (1024 * 1024 + 1), headers=headers).status_code == 413
    assert client.post("/bot/token", content=b"{", headers=headers).status_code == 400


def test_rest_link_uses_bearer_identity(client, monkeypatch):
    monkeypatch.setattr(db, "get_user_by_token", lambda _: {"email": "owner@example.com", "ativo": True})
    create = MagicMock(return_value="link_example")
    monkeypatch.setattr(db, "create_bot_link", create)
    response = client.post("/token/link", headers={"Authorization": "Bearer user"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["callback_url"].endswith("/api/bot/token")
    create.assert_called_once_with("owner@example.com")


def test_rest_link_requires_user(client, monkeypatch):
    monkeypatch.setattr(db, "get_user_by_token", lambda _: None)
    assert client.post("/token/link", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post("/token/link").status_code in (401, 403)


async def test_mcp_uses_session_identity(monkeypatch):
    monkeypatch.setattr(mcp_server, "_current_email", lambda: "owner@example.com")
    monkeypatch.setattr(mcp_server, "_rate_ok", lambda _: True)
    issue = MagicMock(return_value={"link_token": "link_test"})
    monkeypatch.setattr(bot_link, "issue_link", issue)
    fn = getattr(mcp_server.criar_vinculo_bot, "fn", mcp_server.criar_vinculo_bot)
    assert await fn() == {"link_token": "link_test"}
    issue.assert_called_once_with("owner@example.com")
    monkeypatch.setattr(mcp_server, "_current_email", lambda: None)
    issue.reset_mock()
    assert "erro" in await fn()
    issue.assert_not_called()


def mock_connection(monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(db, "_conn", lambda: conn)
    return conn


def test_db_link_hash_and_active_gate(monkeypatch):
    conn = mock_connection(monkeypatch)
    conn.execute.return_value.fetchone.return_value = ("owner@example.com",)
    code = db.create_bot_link("owner@example.com")
    query, params = conn.execute.call_args.args
    assert len(code) == 48
    assert params == (db._hash_token(code), "owner@example.com")
    assert "ativo = true" in query and "10 minutes" in query
    conn.execute.return_value.fetchone.return_value = None
    with pytest.raises(PermissionError):
        db.create_bot_link("inactive@example.com")


def test_db_atomic_encryption_and_replay_gate(monkeypatch, payload):
    conn = mock_connection(monkeypatch)
    conn.execute.return_value.fetchone.return_value = ("person@example.com",)
    assert db.save_bot_storage_state(payload["link_token"], payload["storage_state"], "person@example.com") == "person@example.com"
    calls = conn.execute.call_args_list
    query, params = calls[0].args
    for condition in ("usado_em IS NULL", "expires_at > now()", "u.ativo = true", "lower(link.email) = %s"):
        assert condition in query
    assert params[0] == db._hash_token(payload["link_token"])
    encrypted = calls[1].args[1][1]
    assert "private-cookie" not in encrypted
    assert json.loads(db._fernet.decrypt(encrypted.encode())) == payload["storage_state"]
    assert len(calls) == 3  # consume, save, audit within the same connection context
    conn.commit.assert_not_called()  # psycopg context commits only on successful exit
    assert conn.__exit__.call_args.args == (None, None, None)


def test_db_rejected_link_never_writes_session(monkeypatch, payload):
    conn = mock_connection(monkeypatch)
    conn.execute.return_value.fetchone.return_value = None
    assert db.save_bot_storage_state(payload["link_token"], payload["storage_state"], "wrong@example.com") is None
    assert conn.execute.call_count == 1


def test_db_save_failure_exits_transaction_with_error(monkeypatch, payload):
    conn = mock_connection(monkeypatch)
    cur = MagicMock()
    cur.fetchone.return_value = ("person@example.com",)
    conn.execute.side_effect = [cur, RuntimeError("save failed")]
    with pytest.raises(RuntimeError):
        db.save_bot_storage_state(payload["link_token"], payload["storage_state"], "person@example.com")
    assert conn.__exit__.call_args.args[0] is RuntimeError
    conn.commit.assert_not_called()
