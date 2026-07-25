from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from ..client import AppCtx
from ..normalize import post_to_dict

FetchHistory = Callable[..., Awaitable[Any]]


def next_cursor(items: list[dict[str, Any]], expected: int) -> int | None:
    """Cursor for the next backward page, or None when the page was short.

    ``time`` can be missing on service events, in which case there is nothing to
    page from and the caller must stop rather than subtract from ``None``.
    """
    if len(items) < expected:
        return None
    last_time = items[-1].get("time")
    return last_time - 1 if last_time is not None else None


async def collect_posts(
    fetch: FetchHistory,
    channel_id: int,
    *,
    since_time: int | None,
    max_posts: int,
    before_time: int | None,
    batch: int = 100,
) -> dict[str, Any]:
    """Walk a channel backward from ``before_time`` and collect up to ``max_posts``.

    Returns the posts plus ``next_before_time``: the cursor to pass back in to
    continue past ``max_posts``, or None when the channel (or ``since_time``)
    was reached.
    """
    posts: list[dict[str, Any]] = []
    cursor = before_time
    stopped = "exhausted"
    next_before_time: int | None = None

    while len(posts) < max_posts:
        page = await fetch(chat_id=channel_id, backward=batch, from_time=cursor)
        page = page or []
        if not page:
            break

        stop = False
        for m in page:
            d = post_to_dict(m)
            t = d.get("time")
            if since_time is not None and t is not None and t < since_time:
                stop = True
                stopped = "since_time"
                break
            posts.append(d)
            if len(posts) >= max_posts:
                stop = True
                stopped = "max_posts"
                next_before_time = t - 1 if t is not None else None
                break
        if stop:
            break
        if len(page) < batch:
            break

        cursor = next_cursor([post_to_dict(m) for m in page], batch)
        if cursor is None:
            break

    return {
        "posts": posts,
        "count": len(posts),
        "stopped_reason": stopped,
        "next_before_time": next_before_time,
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_channel_posts(
        ctx: Context[ServerSession, AppCtx],
        channel_id: int,
        limit: int = 50,
        before_time: int | None = None,
    ) -> dict[str, Any]:
        """List recent posts of a MAX channel (backward pagination via `before_time`, unix int)."""
        client = ctx.request_context.lifespan_context.client
        page = await client.fetch_history(
            chat_id=channel_id, backward=limit, from_time=before_time
        )
        page = page or []
        posts = [post_to_dict(m) for m in page]
        return {"posts": posts, "next_before_time": next_cursor(posts, limit)}

    @mcp.tool()
    async def dump_channel(
        ctx: Context[ServerSession, AppCtx],
        channel_id: int,
        since_time: int | None = None,
        max_posts: int = 1000,
        before_time: int | None = None,
    ) -> dict[str, Any]:
        """Dump channel posts backward until `max_posts` or `since_time` reached.

        Hard cap 1000 posts per call to fit MCP output limits. Start with
        `before_time` unset; to go further back, call again passing the
        `next_before_time` returned by the previous call (None means the
        channel, or `since_time`, was reached).
        """
        client = ctx.request_context.lifespan_context.client
        return await collect_posts(
            client.fetch_history,
            channel_id,
            since_time=since_time,
            max_posts=min(max_posts, 1000),
            before_time=before_time,
        )
