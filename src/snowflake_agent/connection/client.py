"""Thin wrapper around snowflake-connector-python.

Every other layer (agent tools, optimizer, cost analyzer) talks to Snowflake
through `SnowflakeClient` so auth, query tagging, and timeouts live in one place.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

import snowflake.connector
from cryptography.hazmat.primitives import serialization
from snowflake.connector import DictCursor, SnowflakeConnection
from snowflake.connector.errors import DatabaseError, ProgrammingError

from snowflake_agent.config import AuthMethod, SnowflakeConfig

logger = logging.getLogger(__name__)


class SnowflakeConnectionError(RuntimeError):
    pass


def _load_private_key(path: str, passphrase: str | None) -> bytes:
    """Load a PEM private key and return it in DER (PKCS8) form, as the connector expects."""
    with open(os.path.expanduser(path), "rb") as f:
        key = serialization.load_pem_private_key(
            f.read(),
            password=passphrase.encode() if passphrase else None,
        )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class SnowflakeClient:
    def __init__(self, config: SnowflakeConfig | None = None):
        self.config = config or SnowflakeConfig.from_env()
        self._conn: SnowflakeConnection | None = None

    # ---------- connection lifecycle ----------

    def _connect_params(self) -> dict[str, Any]:
        c = self.config
        params: dict[str, Any] = {
            "account": c.account,
            "user": c.user,
            "warehouse": c.warehouse,
            "database": c.database,
            "schema": c.schema,
            "role": c.role,
            "login_timeout": c.login_timeout,
            "network_timeout": c.network_timeout,
            "application": "snowflake-agent",
            # Tag every query so the agent's own spend is identifiable in QUERY_HISTORY.
            "session_parameters": {"QUERY_TAG": c.query_tag},
        }
        if c.auth_method is AuthMethod.PASSWORD:
            params["password"] = c.password
        elif c.auth_method is AuthMethod.KEY_PAIR:
            params["private_key"] = _load_private_key(c.private_key_path, c.private_key_passphrase)
        elif c.auth_method is AuthMethod.BROWSER:
            params["authenticator"] = "externalbrowser"
        return {k: v for k, v in params.items() if v is not None}

    def connect(self) -> SnowflakeConnection:
        if self._conn is not None and not self._conn.is_closed():
            return self._conn
        try:
            self._conn = snowflake.connector.connect(**self._connect_params())
        except DatabaseError as e:
            raise SnowflakeConnectionError(f"Failed to connect to Snowflake: {e}") from e
        logger.info("Connected to Snowflake account=%s user=%s", self.config.account, self.config.user)
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            self._conn.close()
            logger.info("Snowflake connection closed")
        self._conn = None

    def __enter__(self) -> "SnowflakeClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------- querying ----------

    @contextmanager
    def cursor(self, as_dict: bool = True) -> Iterator[Any]:
        cur = self.connect().cursor(DictCursor) if as_dict else self.connect().cursor()
        try:
            yield cur
        finally:
            cur.close()

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | tuple | None = None,
        timeout: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run a statement and return all rows as dicts."""
        with self.cursor() as cur:
            try:
                cur.execute(sql, params, timeout=timeout)
            except ProgrammingError as e:
                logger.error("Query failed (query_id=%s): %s", getattr(e, "sfqid", None), e.msg)
                raise
            return cur.fetchall()

    def test_connection(self) -> dict[str, Any]:
        """Return the current session context; raises if the connection is unusable."""
        row = self.execute(
            """
            SELECT CURRENT_ACCOUNT()   AS account,
                   CURRENT_REGION()    AS region,
                   CURRENT_USER()      AS "USER",
                   CURRENT_ROLE()      AS role,
                   CURRENT_WAREHOUSE() AS warehouse,
                   CURRENT_DATABASE()  AS database,
                   CURRENT_SCHEMA()    AS schema,
                   CURRENT_VERSION()   AS version
            """
        )[0]
        return {k.lower(): v for k, v in row.items()}
