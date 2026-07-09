"""
HTTP page fetcher — fetches a URL and returns clean plain text.
Uses httpx for async requests; BeautifulSoup for HTML → text extraction.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, MAX_RETRIES

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Tags we never want content from — strips nav, ads, footers, etc.
IGNORE_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}

# Max characters extracted per page (keeps LLM context manageable)
MAX_CHARS = 12_000


def _html_to_text(html: str) -> str:
    """Extract readable text from HTML, removing boilerplate."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noisy tags
    for tag in soup(IGNORE_TAGS):
        tag.decompose()

    # Prefer main content containers
    for selector in ("#content", "main", "article", ".docs-content", ".documentation"):
        container = soup.select_one(selector)
        if container:
            text = container.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return text[:MAX_CHARS]

    # Fallback to full body text
    text = soup.get_text(separator="\n", strip=True)
    # Collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_CHARS]


async def fetch_page(
    url: str,
    retries: int = MAX_RETRIES,
    timeout: int = HTTP_TIMEOUT,
) -> Optional[str]:
    """
    Fetch a URL and return clean extracted text, or None on failure.
    Retries up to `retries` times with exponential backoff.
    """
    last_exc: Optional[Exception] = None

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=timeout,
        verify=False,   # Some dev-doc sites have cert issues
    ) as client:
        for attempt in range(1, retries + 1):
            try:
                resp = await client.get(url)
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type or "text/" in content_type:
                    return _html_to_text(resp.text)
                elif "application/json" in content_type:
                    return resp.text[:MAX_CHARS]
                else:
                    # Binary / unknown — return empty
                    return ""

            except httpx.HTTPStatusError as exc:
                logger.debug("HTTP %s for %s (attempt %d)", exc.response.status_code, url, attempt)
                last_exc = exc
                if exc.response.status_code in (403, 404, 410):
                    break   # No point retrying
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.debug("Fetch error for %s (attempt %d): %s", url, attempt, exc)
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(2 ** attempt)  # exponential backoff

    logger.warning("Failed to fetch %s after %d attempts: %s", url, retries, last_exc)
    return None


def fetch_page_sync(url: str) -> Optional[str]:
    """Sync wrapper for use inside LangChain tool callables."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, fetch_page(url)).result(timeout=30)
        return loop.run_until_complete(fetch_page(url))
    except Exception as exc:
        logger.error("fetch_page_sync failed for %s: %s", url, exc)
        return None
