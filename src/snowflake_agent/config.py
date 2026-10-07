"""Configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv

load_dotenv()


class AuthMethod(str, Enum):
    PASSWORD = "password"
    KEY_PAIR = "key_pair"
    BROWSER = "externalbrowser"  # SSO via browser


class ConfigError(ValueError):
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) and value.strip() else default


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    auth_method: AuthMethod
    warehouse: str | None = None
    database: str | None = None
    schema: str | None = None
    role: str | None = None
    password: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = None
    query_tag: str = "snowflake-agent"
    login_timeout: int = 60
    network_timeout: int = 300

    @classmethod
    def from_env(cls) -> "SnowflakeConfig":
        account = _env("SNOWFLAKE_ACCOUNT")
        user = _env("SNOWFLAKE_USER")
        if not account or not user:
            raise ConfigError("SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER must be set.")

        try:
            auth_method = AuthMethod(_env("SNOWFLAKE_AUTH_METHOD", "password").lower())
        except ValueError as e:
            valid = ", ".join(m.value for m in AuthMethod)
            raise ConfigError(f"SNOWFLAKE_AUTH_METHOD must be one of: {valid}") from e

        config = cls(
            account=account,
            user=user,
            auth_method=auth_method,
            warehouse=_env("SNOWFLAKE_WAREHOUSE"),
            database=_env("SNOWFLAKE_DATABASE"),
            schema=_env("SNOWFLAKE_SCHEMA"),
            role=_env("SNOWFLAKE_ROLE"),
            password=_env("SNOWFLAKE_PASSWORD"),
            private_key_path=_env("SNOWFLAKE_PRIVATE_KEY_PATH"),
            private_key_passphrase=_env("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
            query_tag=_env("SNOWFLAKE_QUERY_TAG", "snowflake-agent"),
            login_timeout=int(_env("SNOWFLAKE_LOGIN_TIMEOUT", "60")),
            network_timeout=int(_env("SNOWFLAKE_NETWORK_TIMEOUT", "300")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.auth_method is AuthMethod.PASSWORD and not self.password:
            raise ConfigError("SNOWFLAKE_PASSWORD is required for password auth.")
        if self.auth_method is AuthMethod.KEY_PAIR:
            if not self.private_key_path:
                raise ConfigError("SNOWFLAKE_PRIVATE_KEY_PATH is required for key_pair auth.")
            if not os.path.isfile(os.path.expanduser(self.private_key_path)):
                raise ConfigError(f"Private key not found: {self.private_key_path}")
