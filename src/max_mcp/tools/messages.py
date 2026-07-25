from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from ..client import AppCtx
from ..normalize import message_to_dict
from .channels import next_cursor


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def read_messages(
        ctx: Context[ServerSession, AppCtx],
        chat_id: int,
        limit: int = 50,
        before_time: int | None = None,
    ) -> dict[str, Any]:
        """Read message history of a chat. Paginate backward via `before_time` (unix int)."""
        client = ctx.request_context.lifespan_context.client
        page = await client.fetch_history(
            chat_id=chat_id, backward=limit, from_time=before_time
        )
        page = page or []
        messages = [message_to_dict(m) for m in page]
        return {"messages": messages, "next_before_time": next_cursor(messages, limit)}

    @mcp.tool()
    async def search_messages(
        ctx: Context[ServerSession, AppCtx],
        query: str,
        chat_id: int,
        limit: int = 50,
        scan_limit: int = 500,
    ) -> dict[str, Any]:
        """Client-side search: scan up to `scan_limit` messages in `chat_id`, filter by `query`.

        MAX has no native server-side message search. Walks history backward
        in batches of 100 and filters text case-insensitively. Slow on large chats.
        """
        client = ctx.request_context.lifespan_context.client
        q = query.casefold()
        hits: list[dict[str, Any]] = []
        before_time: int | None = None
        scanned = 0
        batch = 100
        while scanned < scan_limit and len(hits) < limit:
            page = await client.fetch_history(
                chat_id=chat_id, backward=batch, from_time=before_time
            )
            page = page or []
            if not page:
                break
            for m in page:
                scanned += 1
                d = message_to_dict(m)
                text = (d.get("text") or "").casefold()
                if q in text:
                    hits.append(d)
                    if len(hits) >= limit:
                        break
            if len(page) < batch:
                break
            last_time = page[-1].time if hasattr(page[-1], "time") else message_to_dict(page[-1]).get("time")
            if last_time is None:
                break
            before_time = last_time - 1
        return {
            "messages": hits,
            "scanned": scanned,
            "scan_exhausted": scanned >= scan_limit,
        }
