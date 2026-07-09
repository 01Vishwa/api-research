"""
Composio client — initialises a Composio session and exposes search/fetch tools
formatted for LangChain/LangGraph agents.

Exact API used (Composio v0.17.x):
    from composio import Composio
    from composio_langchain import LangchainProvider

    composio = Composio(provider=LangchainProvider(), api_key=COMPOSIO_API_KEY)
    session  = composio.create(          # shortcut for composio.sessions.create()
        user_id="agentforge-researcher",
        manage_connections={"wait_for_connections": True},
    )
    tools = session.tools()              # returns list[StructuredTool] for LangChain
"""

from __future__ import annotations

import logging
from typing import Optional

from config import (
    COMPOSIO_API_KEY,
    COMPOSIO_USER_ID,
    USE_COMPOSIO_SEARCH,
)

logger = logging.getLogger(__name__)

# ─── Composio session (lazy singleton) ───────────────────────────────────────

_composio_session = None
_composio_tools: list = []


def _build_composio_session():
    """Build and return a Composio session with LangChain provider."""
    global _composio_session

    if _composio_session is not None:
        return _composio_session

    try:
        from composio import Composio
        from composio_langchain import LangchainProvider

        # LangchainProvider wraps tools as langchain StructuredTool objects
        composio = Composio(
            provider=LangchainProvider(),
            api_key=COMPOSIO_API_KEY,
        )

        # composio.create is a top-level shortcut for composio.sessions.create()
        # Confirmed in composio SDK source: self.create = self._sessions.create
        session = composio.create(
            user_id=COMPOSIO_USER_ID,
            manage_connections={
                "wait_for_connections": True,
            },
        )

        _composio_session = session
        logger.info("✅ Composio session created (user_id=%s)", COMPOSIO_USER_ID)
        return session

    except Exception as exc:
        logger.warning(
            "⚠️  Could not create Composio session: %s — falling back to Tavily + httpx.",
            exc,
        )
        return None


def get_composio_tools() -> list:
    """
    Return LangChain-compatible tools from the Composio session.

    Returns:
        List of LangChain StructuredTool objects (from session.tools()), or []
        if Composio is unavailable. Graceful degradation — never raises.
    """
    global _composio_tools

    if not USE_COMPOSIO_SEARCH:
        logger.debug("Composio search disabled — COMPOSIO_API_KEY not set.")
        return []

    session = _build_composio_session()
    if session is None:
        return []

    try:
        tools = session.tools()   # returns list[StructuredTool] via LangchainProvider
        _composio_tools = list(tools) if tools else []
        logger.info("🔧 Loaded %d Composio tools from session", len(_composio_tools))
        return _composio_tools

    except Exception as exc:
        logger.warning("⚠️  session.tools() failed: %s", exc)
        return []


def get_search_tools_for_agent() -> list:
    """
    Convenience wrapper used by the research and verification agents.
    Returns Composio tools when available, empty list otherwise.
    The agent supplements with its own Tavily search tool regardless.
    """
    return get_composio_tools()
