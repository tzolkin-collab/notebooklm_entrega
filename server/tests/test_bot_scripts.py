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
        "PUBLIC_URL": "https://test.invalid",
        "NOTEBOOKLM_SERVER_URL": "https://test.invalid",
        "NOTEBOOKLM_BOT_CALLBACK_KEY": "k" * 43,
    }
    monkeypatch.setattr(configure, "dotenv_values", lambda *a, **kw: values.copy())
    monkeypatch.setattr(sender, "dotenv_values", lambda *a, **kw: values.copy())
    return values


def test_validate_succeeds(settings):
    assert configure.main([]) == 0


@pytest.mark.parametrize("field,value", [
    ("NOTEBOOKLM_BOT_CALLBACK_KEY", ""),
    ("NOTEBOOKLM_BOT_CALLBACK_KEY", "short"),
    ("PUBLIC_URL", "http://test.invalid"),
    ("NOTEBOOKLM_SERVER_URL", "https://other.invalid"),
])
def test_invalid_configuration_reported(settings, field, value):
    settings[field] = value
    assert configure.main([]) == 1


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
