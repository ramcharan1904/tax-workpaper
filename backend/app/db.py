"""Database connection pool.

The app uses DATABASE_URL, Neon's POOLED connection (hostname contains
-pooler). Neon pools through PgBouncer in transaction mode, so we turn off
psycopg's automatic server-side prepared statements (prepare_threshold=None)
to avoid 'prepared statement already exists' errors behind the pooler.
"""
import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = ConnectionPool(
            url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=True,
        )
    return _pool


def close() -> None:
    if _pool is not None:
        _pool.close()
