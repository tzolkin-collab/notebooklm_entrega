import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


configure = module_at("configure_bot", "scripts/configure_bot.py")
sender = module_at("send_bot_token", "scripts/bot/send_token.py")


@pytest.fixture
def settings(monkeypatch):
    values = {
        "DATABASE_URL": "postgres://user:password@test.invalid/db?sslmode=require",
        "PUBLIC_URL": "https://test.invalid",
        "NOTEBOOKLM_SERVER_URL": "https://test.invalid",
        "NOTEBOOKLM_BOT_CALLBACK_KEY": "k" * 43,
    }
    monkeypatch.setattr(configure, "dotenv_values", lambda *a, **kw: values.copy())
    monkeypatch.setattr(sender, "dotenv_values", lambda *a, **kw: values.copy())
    return values


def test_validate_does_not_connect(settings, monkeypatch):
    connect = MagicMock(side_effect=AssertionError("No network"))
    monkeypatch.setattr(configure.psycopg, "connect", connect)
    assert configure.main([]) == 0
    connect.assert_not_called()


def test_apply_only_link_migration(settings, monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(configure.psycopg, "connect", connect)
    assert configure.main(["--apply"]) == 0
    sql = "\n".join(call.args[0] for call in conn.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS notebooklm.bot_links" in sql
    assert "DROP" not in sql and "UPDATE" not in sql and "DELETE FROM" not in sql
    assert conn.__exit__.call_args.args == (None, None, None)


@pytest.mark.parametrize("field,value", [
    ("NOTEBOOKLM_BOT_CALLBACK_KEY", ""),
    ("NOTEBOOKLM_BOT_CALLBACK_KEY", "short"),
    ("PUBLIC_URL", "http://test.invalid"),
    ("NOTEBOOKLM_SERVER_URL", "https://other.invalid"),
    ("DATABASE_URL", "postgres://u:p@test.invalid/db?sslmode=disable"),
])
def test_invalid_configuration_stops_before_network(settings, monkeypatch, field, value):
    settings[field] = value
    connect = MagicMock(side_effect=AssertionError("No network"))
    monkeypatch.setattr(configure.psycopg, "connect", connect)
    assert configure.main(["--apply"]) == 1
    connect.assert_not_called()


def test_different_keys_rejected(settings, monkeypatch):
    monkeypatch.setattr(configure, "dotenv_values", lambda path, **kw:
                        settings if path == "server" else settings | {"NOTEBOOKLM_BOT_CALLBACK_KEY": "x" * 43})
    with pytest.raises(ValueError, match="iguais"):
        configure.read_settings("server", "bot")


def test_send_contract(settings, monkeypatch):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = b'{"status":"ok","email":"person@test.invalid"}'
    monkeypatch.setattr(sender, "build_opener", lambda _: opener)
    assert sender.send_token("code", "person@test.invalid", {"cookies": []}) == {"status": "ok"}
    req = opener.open.call_args.args[0]
    assert req.full_url == "https://test.invalid/api/bot/token"
    assert sender.json.loads(req.data)["link_token"] == "code"
    assert req.get_header("X-bot-key") == settings["NOTEBOOKLM_BOT_CALLBACK_KEY"]


def test_no_redirect_or_secret_in_errors(settings, monkeypatch):
    assert sender.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid") is None
    opener = MagicMock()
    opener.open.side_effect = sender.HTTPError("https://test.invalid", 403, "private-secret", {}, None)
    monkeypatch.setattr(sender, "build_opener", lambda _: opener)
    with pytest.raises(RuntimeError) as error:
        sender.send_token("private-code", "person@test.invalid", {})
    assert "403" in str(error.value)
    assert "private" not in str(error.value)
