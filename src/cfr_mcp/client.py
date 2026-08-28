"""Thin async client over the eCFR public API.

Every endpoint path lives in ENDPOINTS below. If the API changes, this dict
is the only thing that needs editing.

No API key, no registration. See 1 CFR 2.6 for reproduction rights.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import httpx

from .cache import Cache
from .citations import Citation

BASE_URL = "https://www.ecfr.gov"

USER_AGENT = (
    "cfr-mcp/0.1 (+https://github.com/YOURNAME/cfr-mcp) "
    "unofficial MCP server; contact: YOUR_EMAIL"
)

ENDPOINTS = {
    # --- Admin service: metadata (JSON) ---
    "agencies": "/api/admin/v1/agencies.json",
    "corrections": "/api/admin/v1/corrections.json",
    "corrections_by_title": "/api/admin/v1/corrections/title/{title}.json",
    # --- Search service ---
    "search": "/api/search/v1/results",
    "search_count": "/api/search/v1/count",
    "search_summary": "/api/search/v1/summary",
    "counts_daily": "/api/search/v1/counts/daily",
    "counts_titles": "/api/search/v1/counts/titles",
    "counts_hierarchy": "/api/search/v1/counts/hierarchy",
    "suggestions": "/api/search/v1/suggestions",
    # --- Versioner service: content and structure ---
    "titles": "/api/versioner/v1/titles.json",
    "ancestry": "/api/versioner/v1/ancestry/{date}/title-{title}.json",
    "full_xml": "/api/versioner/v1/full/{date}/title-{title}.xml",
    "structure": "/api/versioner/v1/structure/{date}/title-{title}.json",
    "versions": "/api/versioner/v1/versions/title-{title}.json",
}


class ECFRError(RuntimeError):
    """Upstream API returned something we cannot use."""


class ECFRClient:
    """Async client with disk caching and polite retry.

    The eCFR publishes no documented rate limit, so we self-limit: a small
    concurrency cap plus aggressive caching. Historical dates are immutable
    and cached forever; current-date responses expire after a day.
    """

    def __init__(
        self,
        cache: Cache | None = None,
        *,
        timeout: float = 30.0,
        max_concurrency: int = 4,
    ) -> None:
        self._cache = cache or Cache()
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(max_concurrency)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ECFRClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---------------- core fetch ----------------

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        immutable: bool = False,
        attempts: int = 3,
    ) -> str:
        key = self._cache.key(path, params)
        if (hit := self._cache.get(key)) is not None:
            return hit

        last: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._sem:
                    resp = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                last = exc
                await asyncio.sleep(2**attempt)
                continue

            if resp.status_code == 404:
                raise ECFRError(
                    f"Not found: {path}. For versioner routes this usually means "
                    "the date is not a valid issue date for that title, or the "
                    "part/section does not exist on that date."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                last = ECFRError(f"HTTP {resp.status_code} from {path}")
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()

            self._cache.set(key, resp.text, immutable=immutable)
            return resp.text

        raise ECFRError(f"Failed after {attempts} attempts: {last}")

    async def _get_json(self, path: str, params=None, *, immutable=False) -> Any:
        import json

        return json.loads(await self._get(path, params, immutable=immutable))

    # ---------------- date handling ----------------

    async def latest_date_for_title(self, title: int) -> str:
        """Resolve a valid issue date for a title.

        The versioner routes take a date in the path and 404 on dates that are
        not valid issue dates for that title. Never pass today's date blindly;
        always resolve through titles.json first.
        """
        data = await self._get_json(ENDPOINTS["titles"])
        for entry in data.get("titles", []):
            if int(entry.get("number", -1)) == title:
                date = entry.get("latest_issue_date") or entry.get("up_to_date_as_of")
                if not date:
                    raise ECFRError(f"No issue date reported for title {title}")
                return str(date)
        raise ECFRError(f"Unknown CFR title: {title}")

    async def _resolve_date(self, title: int, date: str | None) -> tuple[str, bool]:
        """Return (date, immutable). Past dates never change, so cache forever."""
        if date is None:
            return await self.latest_date_for_title(title), False
        try:
            parsed = dt.date.fromisoformat(date)
        except ValueError as exc:
            raise ECFRError(f"Date must be YYYY-MM-DD, got {date!r}") from exc
        return date, parsed < dt.date.today() - dt.timedelta(days=1)

    # ---------------- public surface ----------------

    async def titles(self) -> Any:
        return await self._get_json(ENDPOINTS["titles"])

    async def agencies(self) -> Any:
        return await self._get_json(ENDPOINTS["agencies"])

    async def structure(self, title: int, date: str | None = None) -> Any:
        resolved, immutable = await self._resolve_date(title, date)
        path = ENDPOINTS["structure"].format(date=resolved, title=title)
        return await self._get_json(path, immutable=immutable)

    async def ancestry(self, cit: Citation, date: str | None = None) -> Any:
        resolved, immutable = await self._resolve_date(cit.title, date)
        path = ENDPOINTS["ancestry"].format(date=resolved, title=cit.title)
        return await self._get_json(path, cit.as_params(), immutable=immutable)

    async def full_xml(self, cit: Citation, date: str | None = None) -> str:
        """Raw XML for a part/subpart/section/appendix.

        Guard rail: a bare title request returns an entire downloadable XML
        document (hundreds of MB for some titles). We refuse it outright.
        """
        if cit.is_title_only:
            raise ECFRError(
                "Refusing a title-level XML request: the API returns the entire "
                "title as a downloadable document. Specify at least a part."
            )
        resolved, immutable = await self._resolve_date(cit.title, date)
        path = ENDPOINTS["full_xml"].format(date=resolved, title=cit.title)
        return await self._get(path, cit.as_params(), immutable=immutable)

    async def versions(self, title: int, params: dict[str, Any] | None = None) -> Any:
        path = ENDPOINTS["versions"].format(title=title)
        return await self._get_json(path, params)

    async def corrections_for_title(self, title: int) -> Any:
        path = ENDPOINTS["corrections_by_title"].format(title=title)
        return await self._get_json(path)

    async def search(self, query: str, **params: Any) -> Any:
        return await self._get_json(
            ENDPOINTS["search"], {"query": query, **params}
        )

    async def search_count(self, query: str, **params: Any) -> Any:
        return await self._get_json(
            ENDPOINTS["search_count"], {"query": query, **params}
        )

    async def counts_hierarchy(self, query: str, **params: Any) -> Any:
        """Where in the CFR a term appears, without fetching any text."""
        return await self._get_json(
            ENDPOINTS["counts_hierarchy"], {"query": query, **params}
        )

    async def counts_daily(self, query: str, **params: Any) -> Any:
        return await self._get_json(
            ENDPOINTS["counts_daily"], {"query": query, **params}
        )
