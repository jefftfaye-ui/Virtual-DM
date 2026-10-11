"""Rules lookup — three-stage match: exact name_norm → trigram → FTS.

Requires pg_trgm extension (already in schema).
"""

from __future__ import annotations

import os

from db import repo
from rules.statblock import normalize_name


_MAX_BODY = 1500  # chars returned per rule chunk


def _trim(body: str, limit: int = _MAX_BODY) -> str:
    if len(body) <= limit:
        return body
    return body[:limit].rsplit("\n", 1)[0] + "\n…"


async def _lookup_impl(
    conn,
    query: str,
    edition: str,
    kind: str | None,
    is_monster: bool,
) -> dict:
    norm = normalize_name(query)
    kind_filter = "AND kind=%s" if kind else ""
    kind_args: tuple = (kind,) if kind else ()

    # Stage 1: exact name_norm
    rows = await repo.fetchall(
        conn,
        f"SELECT id, name, kind, body, meta FROM srd_chunks "
        f"WHERE edition=%s AND name_norm=%s {kind_filter} LIMIT 3",
        (edition, norm) + kind_args,
    )
    if rows:
        stage = "exact"
    else:
        # Stage 2: trigram similarity
        rows = await repo.fetchall(
            conn,
            f"SELECT id, name, kind, body, meta, similarity(name_norm, %s) AS sim "
            f"FROM srd_chunks WHERE edition=%s {kind_filter} "
            f"AND similarity(name_norm, %s) > 0.3 "
            f"ORDER BY sim DESC LIMIT 3",
            (norm, edition) + kind_args + (norm,),
        )
        if rows:
            stage = "trigram"
        else:
            # Stage 3: full-text
            rows = await repo.fetchall(
                conn,
                f"SELECT id, name, kind, body, meta, ts_rank(tsv, websearch_to_tsquery('english', %s)) AS rank "
                f"FROM srd_chunks WHERE edition=%s {kind_filter} "
                f"AND tsv @@ websearch_to_tsquery('english', %s) "
                f"ORDER BY rank DESC LIMIT 3",
                (query, edition) + kind_args + (query,),
            )
            stage = "fts"

    if not rows:
        return {"results": [], "query": query, "stage": "none", "hint": "not found in SRD"}

    results = []
    for r in rows:
        body = r["body"] or ""
        entry: dict = {
            "name": r["name"],
            "kind": r["kind"],
            "matched_stage": stage,
            "body": body if is_monster else _trim(body),
        }
        if is_monster and r.get("meta"):
            entry["meta"] = r["meta"]
        results.append(entry)

    return {"results": results, "query": query, "stage": stage}


async def _get_edition(conn, campaign_id: str) -> str:
    row = await repo.fetchone(conn, "SELECT edition FROM campaigns WHERE id=%s", (campaign_id,))
    return str(row["edition"]) if row else "2014"


def _campaign_id() -> str | None:
    return os.environ.get("DEFAULT_CAMPAIGN_ID")


async def lookup_rule(query: str, kind: str | None = None) -> dict:
    """Three-stage SRD rule lookup: exact → trigram → FTS.
    kind: rule | spell | condition | item | monster (or None for all).
    Returns top 3 chunks trimmed to ~1500 chars each."""
    from db import repo as _repo
    cid = _campaign_id()
    async with _repo.tx() as conn:
        edition = await _get_edition(conn, cid) if cid else "2014"
        return await _lookup_impl(conn, query, edition, kind, is_monster=False)


async def lookup_monster(name: str) -> dict:
    """Three-stage SRD monster lookup. Returns full stat block body + structured meta."""
    from db import repo as _repo
    cid = _campaign_id()
    async with _repo.tx() as conn:
        edition = await _get_edition(conn, cid) if cid else "2014"
        return await _lookup_impl(conn, name, edition, "monster", is_monster=True)


# ─── internal helper used by start_encounter ──────────────────────────────────

async def _lookup_monster_meta(conn, name: str, edition: str) -> dict | None:
    """Return the meta dict for a monster by name. Used by start_encounter.
    Returns None if not found.
    """
    norm = normalize_name(name)
    # exact first
    row = await repo.fetchone(
        conn,
        "SELECT meta FROM srd_chunks WHERE edition=%s AND kind='monster' AND name_norm=%s LIMIT 1",
        (edition, norm),
    )
    if row and row.get("meta"):
        return row["meta"]
    # trigram fallback
    row = await repo.fetchone(
        conn,
        "SELECT meta FROM srd_chunks WHERE edition=%s AND kind='monster' "
        "AND similarity(name_norm, %s) > 0.4 "
        "ORDER BY similarity(name_norm, %s) DESC LIMIT 1",
        (edition, norm, norm),
    )
    if row and row.get("meta"):
        return row["meta"]
    return None
