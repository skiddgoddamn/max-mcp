from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from ..client import AppCtx
from ..normalize import message_to_dict, user_to_dict


def _my_id(client: Any) -> int:
    """The logged-in account's own user id (needed to derive 1:1 chat ids)."""
    me = getattr(client, "me", None)
    contact = getattr(me, "contact", None) if me is not None else None
    my_id = getattr(contact, "id", None)
    if my_id is None:
        raise RuntimeError("Own profile not loaded yet — is the session logged in?")
    return my_id


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def find_user_by_phone(
        ctx: Context[ServerSession, AppCtx],
        phone: str,
    ) -> dict[str, Any] | None:
        """Resolve a MAX user by phone number (E.164, e.g. +79991234567).

        Returns the user's id, display name and profile, or raises if the number
        is not registered on MAX. Feed the id to add_contact / get_dialog_chat_id,
        or use send_message_by_phone to do it all in one call.
        """
        client = ctx.request_context.lifespan_context.client
        return user_to_dict(await client.search_by_phone(phone))

    @mcp.tool()
    async def get_user(
        ctx: Context[ServerSession, AppCtx],
        user_id: int,
    ) -> dict[str, Any] | None:
        """Fetch a MAX user's profile by id (cache first, then server). None if unknown."""
        client = ctx.request_context.lifespan_context.client
        return user_to_dict(await client.get_user(user_id))

    @mcp.tool()
    async def list_contacts(
        ctx: Context[ServerSession, AppCtx],
    ) -> dict[str, Any]:
        """List the account's saved contacts."""
        client = ctx.request_context.lifespan_context.client
        contacts = [user_to_dict(u) for u in (client.contacts or []) if u]
        return {"contacts": contacts, "count": len(contacts)}

    @mcp.tool()
    async def add_contact(
        ctx: Context[ServerSession, AppCtx],
        user_id: int,
    ) -> dict[str, Any] | None:
        """Add a user to the account's contacts by id."""
        client = ctx.request_context.lifespan_context.client
        return user_to_dict(await client.add_contact(user_id))

    @mcp.tool()
    async def remove_contact(
        ctx: Context[ServerSession, AppCtx],
        user_id: int,
    ) -> dict[str, Any]:
        """Remove a user from the account's contacts by id."""
        client = ctx.request_context.lifespan_context.client
        await client.remove_contact(user_id)
        return {"removed": True, "user_id": user_id}

    @mcp.tool()
    async def import_contacts(
        ctx: Context[ServerSession, AppCtx],
        contacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Bulk-resolve phone numbers to MAX users (phone-book import).

        Each item is {"phone": "+7...", "first_name": "...", "last_name": "..."}
        (last_name optional). Returns the MAX users the server matched.
        """
        from pymax.types import ContactInfo

        infos: list[ContactInfo] = []
        for c in contacts:
            phone = c.get("phone")
            if not phone:
                raise ValueError("each contact needs a 'phone'")
            infos.append(
                ContactInfo(
                    phone=str(phone),
                    first_name=c.get("first_name") or "",
                    last_name=c.get("last_name"),
                )
            )
        client = ctx.request_context.lifespan_context.client
        matched = [user_to_dict(u) for u in await client.import_contacts(infos) if u]
        return {"matched": matched, "count": len(matched)}

    @mcp.tool()
    async def get_dialog_chat_id(
        ctx: Context[ServerSession, AppCtx],
        user_id: int,
    ) -> dict[str, Any]:
        """Compute the 1:1 dialog chat_id with a user (local XOR, no request).

        Feed the returned chat_id to send_message / read_messages.
        """
        client = ctx.request_context.lifespan_context.client
        chat_id = client.get_chat_id(_my_id(client), user_id)
        return {"chat_id": chat_id, "user_id": user_id}

    @mcp.tool()
    async def send_message_by_phone(
        ctx: Context[ServerSession, AppCtx],
        phone: str,
        text: str,
        add_to_contacts: bool = False,
    ) -> dict[str, Any]:
        """DM a MAX user by phone number in one step.

        Resolves phone -> user, derives the 1:1 dialog, and sends `text`. Set
        add_to_contacts=True to add them first (helps when their privacy blocks
        messages from non-contacts). Raises if the number isn't on MAX.
        """
        client = ctx.request_context.lifespan_context.client
        user = await client.search_by_phone(phone)
        user_id = getattr(user, "id", None)
        if user_id is None:
            raise RuntimeError(f"No MAX user found for phone {phone}")
        if add_to_contacts:
            await client.add_contact(user_id)
        chat_id = client.get_chat_id(_my_id(client), user_id)
        sent = await client.send_message(chat_id=chat_id, text=text)
        result = message_to_dict(sent)
        result["chat_id"] = chat_id
        result["user"] = user_to_dict(user)
        return result
