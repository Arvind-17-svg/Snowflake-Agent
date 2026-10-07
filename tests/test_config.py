import pytest

from snowflake_agent.config import AuthMethod, ConfigError, SnowflakeConfig
from snowflake_agent.connection import SnowflakeClient


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_AUTH_METHOD",
                "SNOWFLAKE_PASSWORD", "SNOWFLAKE_PRIVATE_KEY_PATH", "SNOWFLAKE_WAREHOUSE"):
        monkeypatch.delenv(var, raising=False)


def test_missing_account_raises():
    with pytest.raises(ConfigError):
        SnowflakeConfig.from_env()


def test_password_auth_requires_password(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "org-acct")
    monkeypatch.setenv("SNOWFLAKE_USER", "me")
    with pytest.raises(ConfigError, match="PASSWORD"):
        SnowflakeConfig.from_env()


def test_invalid_auth_method(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "org-acct")
    monkeypatch.setenv("SNOWFLAKE_USER", "me")
    monkeypatch.setenv("SNOWFLAKE_AUTH_METHOD", "magic")
    with pytest.raises(ConfigError):
        SnowflakeConfig.from_env()


def test_connect_params_omit_unset_and_set_query_tag():
    cfg = SnowflakeConfig(account="org-acct", user="me", auth_method=AuthMethod.PASSWORD, password="x")
    params = SnowflakeClient(cfg)._connect_params()
    assert params["password"] == "x"
    assert "warehouse" not in params
    assert params["session_parameters"]["QUERY_TAG"] == "snowflake-agent"


def test_browser_auth_params():
    cfg = SnowflakeConfig(account="org-acct", user="me", auth_method=AuthMethod.BROWSER)
    params = SnowflakeClient(cfg)._connect_params()
    assert params["authenticator"] == "externalbrowser"
    assert "password" not in params
