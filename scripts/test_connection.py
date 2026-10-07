"""Smoke test: python scripts/test_connection.py"""

import logging
import sys

from snowflake_agent.config import ConfigError
from snowflake_agent.connection import SnowflakeClient, SnowflakeConnectionError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    try:
        with SnowflakeClient() as client:
            info = client.test_connection()
    except (ConfigError, SnowflakeConnectionError) as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1

    print("Connected to Snowflake")
    for key, value in info.items():
        print(f"  {key:<10} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
