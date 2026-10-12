"""Thin async repo over psycopg3. One pool per process. Transactions on demand."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


def _dsn() -> str:
    dsn = os.environ.get("SUPABASE_URL")
    if not dsn:
        raise RuntimeError("SUPABASE_URL not set")
    return dsn


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(_dsn(), min_size=1, max_size=10, open=False)
        await _pool.open()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def tx():
    """Yield a connection inside a transaction. Auto-commits on success."""
    if _pool is None:
        await init_pool()
    assert _pool is not None
    async with _pool.connection() as conn:
        async with conn.transaction():
            yield conn


async def fetchone(conn, sql: str, params: tuple | dict | None = None) -> dict | None:
    cur = await conn.execute(sql, params or ())
    row = await cur.fetchone()
    if row is None:
        return None
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


async def fetchall(conn, sql: str, params: tuple | dict | None = None) -> list[dict]:
    cur = await conn.execute(sql, params or ())
    rows = await cur.fetchall()
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


async def execute(conn, sql: str, params: tuple | dict | None = None) -> None:
    await conn.execute(sql, params or ())


# ─── idempotency helper (SPEC §4.7) ────────────────────────────────────


async def check_idempotent(conn, campaign_id: str, request_id: str | None) -> dict | None:
    if not request_id:
        return None
    row = await fetchone(
        conn,
        "SELECT result FROM request_ids WHERE campaign_id = %s AND request_id = %s",
        (campaign_id, request_id),
    )
    return row["result"] if row else None


async def store_idempotent(
    conn, campaign_id: str, request_id: str | None, result: dict
) -> None:
    if not request_id:
        return
    await execute(
        conn,
        "INSERT INTO request_ids (campaign_id, request_id, result) VALUES (%s, %s, %s::jsonb) "
        "ON CONFLICT DO NOTHING",
        (campaign_id, request_id, json.dumps(result)),
    )
