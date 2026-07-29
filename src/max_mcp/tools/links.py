from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pymax import ApiError
from pymax.protocol import Opcode

from ..client import AppCtx
from ..normalize import message_to_dict
from .contacts import _my_id

# Hosts MAX profile/chat links live on. The server's LINK_INFO lookup keys on
# the bare path (e.g. "id2465215235_biz", "u/<token>"), NOT the full URL:
# passing "max.ru/id..._biz" verbatim returns not.found, the bare slug resolves.
_HOSTS = ("max.ru", "oneme.ru")


def _link_slug(link: str) -> str:
    """Reduce any MAX profile/chat link to the bare slug LINK_INFO expects.

    Handles ``https://max.ru/u/<token>``, ``max.ru/id123_biz``, ``u/<token>``
    and bare slugs. Strips scheme, host and query/fragment; keeps the rest of
    the path (the ``u/`` prefix is part of the link name the server stores).
    """
    if not isinstance(link, str) or not link.strip():
        raise ValueError("link must be a non-empty string")
    s = link.strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("?", 1)[0].split("#", 1)[0]
    if "/" in s:
        head, rest = s.split("/", 1)
        # drop a leading host segment (has a dot), keep path segments like "u/"
        if "." in head:
            s = rest
    s = s.strip("/")
    if not s:
        raise ValueError(f"could not extract a MAX link slug from {link!r}")
    return s


def _name_from(contact: dict[str, Any]) -> str | None:
    for n in contact.get("names") or []:
        if not isinstance(n, dict):
            continue
        nm = n.get("name") or " ".join(
            p for p in (n.get("firstName"), n.get("lastName")) if p
        ).strip()
        if nm:
            return nm
    nm = " ".join(
        p for p in (contact.get("firstName"), contact.get("lastName")) if p
    ).strip()
    return nm or None


def _extract(payload: Any, my_id: int | None, link: str, slug: str) -> dict[str, Any]:
    """Turn a raw LINK_INFO payload into a flat, id-first result.

    Groups/channels/business pages come back under ``chat`` (use ``chat.id``
    directly). Personal ``u/`` links come back under ``contact``/``user`` — we
    also derive the 1:1 dialog ``chat_id`` (my_id XOR user_id) so the caller can
    message them straight away. Unknown shapes return ``raw`` for inspection.
    """
    result: dict[str, Any] = {"input": link, "slug": slug}
    p = payload if isinstance(payload, dict) else {}

    chat = p.get("chat")
    if isinstance(chat, dict) and chat.get("id") is not None:
        result.update(
            kind="chat",
            chat_id=chat.get("id"),
            chat_type=str(chat.get("type")) if chat.get("type") is not None else None,
            title=chat.get("title"),
            access=chat.get("access"),
            participants_count=chat.get("participantsCount"),
            canonical_link=chat.get("link"),
        )
        return result

    for key in ("contact", "user"):
        c = p.get(key)
        if isinstance(c, dict) and c.get("id") is not None:
            uid = c.get("id")
            result.update(
                kind="user",
                user_id=uid,
                name=_name_from(c),
                phone=c.get("phone"),
                canonical_link=c.get("link"),
                chat_id=(my_id ^ uid) if my_id is not None else None,
            )
            return result

    result.update(kind="unknown", raw_keys=sorted(p.keys()), raw=p)
    return result


async def _resolve(client: Any, link: str) -> dict[str, Any]:
    slug = _link_slug(link)
    try:
        resp = await client._app.invoke(Opcode.LINK_INFO, {"link": slug})
    except ApiError as e:
        raise RuntimeError(
            f"MAX could not resolve link {link!r} (slug {slug!r}): {e}. "
            "The link may be expired, private, or not a MAX profile link."
        ) from e
    return _extract(getattr(resp, "payload", None), _my_id(client), link, slug)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def resolve_link(
        ctx: Context[ServerSession, AppCtx],
        link: str,
    ) -> dict[str, Any]:
        """Resolve a public MAX link into an id you can message.

        Accepts personal share links (``max.ru/u/<token>``), business/username
        links (``max.ru/id123_biz``, ``max.ru/<name>``), full URLs or bare
        slugs. Returns ``chat_id`` (feed to send_message) plus ``kind``
        (chat/user), ``title``/``name`` and ``chat_type``. For personal ``u/``
        links it also returns ``user_id`` and the derived 1:1 ``chat_id``.
        Raises if MAX can't resolve the link (expired/private/not a MAX link).

        Note: business ``id..._biz`` links are usually public CHANNELs you can't
        DM unless you're an admin — check ``chat_type``/``access``.
        """
        client = ctx.request_context.lifespan_context.client
        return await _resolve(client, link)

    @mcp.tool()
    async def send_message_by_link(
        ctx: Context[ServerSession, AppCtx],
        link: str,
        text: str,
    ) -> dict[str, Any]:
        """Resolve a public MAX link and send ``text`` to it in one call.

        Best for personal share links (``max.ru/u/<token>``): resolves the
        contact, derives the 1:1 dialog and sends. Business ``id..._biz`` links
        resolve to public CHANNELs — sending fails unless you're an admin; use
        resolve_link first if unsure.
        """
        client = ctx.request_context.lifespan_context.client
        resolved = await _resolve(client, link)
        chat_id = resolved.get("chat_id")
        if chat_id is None:
            raise RuntimeError(
                f"resolved {link!r} but got no messageable chat_id "
                f"(kind={resolved.get('kind')}); inspect with resolve_link"
            )
        sent = await client.send_message(chat_id=chat_id, text=text)
        result = message_to_dict(sent)
        result["chat_id"] = chat_id
        result["resolved"] = resolved
        return result
