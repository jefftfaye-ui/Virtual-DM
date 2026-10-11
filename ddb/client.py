"""The ONLY file that knows the D&D Beyond URL/shape.

Isolated per SPEC §3 — if DDB changes shape, fail loudly here.
"""

from __future__ import annotations

import httpx

_DDB_BASE = "https://character-service.dndbeyond.com/character/v5/character"


class DDBError(RuntimeError):
    """DDB fetch failed. Message should include whether to retry locally."""


async def fetch_character(id_: str, *, timeout: float = 15.0) -> dict:
    url = f"{_DDB_BASE}/{id_}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url, headers={"User-Agent": "dm-server/0.1"})
    except httpx.HTTPError as e:
        raise DDBError(
            f"DDB fetch network error: {e}. Run scripts/import_ddb.py from a laptop."
        ) from e
    if r.status_code == 403:
        raise DDBError(
            "DDB blocked the request (likely datacenter IP). "
            "Run scripts/import_ddb.py from a laptop."
        )
    if r.status_code == 404:
        raise DDBError(f"DDB character {id_} not found or not Public.")
    if r.status_code != 200:
        raise DDBError(f"DDB returned {r.status_code}: {r.text[:300]}")
    try:
        payload = r.json()
    except Exception as e:
        raise DDBError(f"DDB payload was not JSON: {e}") from e
    data = payload.get("data")
    if not isinstance(data, dict):
        raise DDBError("DDB payload shape changed: missing top-level `data` object")
    return data


def extract_id(url_or_id: str) -> str:
    """Pull the numeric ID from a DDB URL or return the id as-is."""
    s = url_or_id.strip().rstrip("/")
    if s.isdigit():
        return s
    for sep in ("/characters/", "/character/"):
        if sep in s:
            tail = s.rsplit(sep, 1)[1]
            tail = tail.split("/")[0].split("?")[0]
            if tail.isdigit():
                return tail
    raise DDBError(f"could not extract DDB character id from {url_or_id!r}")
