from typing import Any


def _dump(obj: Any) -> Any:
    if obj is None:
        return None
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    return obj


def chat_to_dict(chat: Any) -> dict[str, Any]:
    d = _dump(chat) or {}
    chat_type = d.get("type") or getattr(chat, "type", None)
    return {
        "id": d.get("id") or getattr(chat, "id", None),
        "title": d.get("title") or getattr(chat, "title", None),
        "type": str(chat_type) if chat_type is not None else None,
        "last_event_time": d.get("last_event_time"),
        "participants_count": d.get("participants_count"),
        "description": d.get("description"),
        "owner_id": d.get("owner"),
    }


def _display_name(names: Any) -> str | None:
    for n in names or []:
        get = n.get if isinstance(n, dict) else lambda k: getattr(n, k, None)
        nm = get("name")
        if not nm:
            nm = " ".join(p for p in (get("first_name"), get("last_name")) if p) or None
        if nm:
            return nm
    return None


def user_to_dict(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    d = _dump(user) or {}
    return {
        "id": d.get("id") or getattr(user, "id", None),
        "name": _display_name(d.get("names")),
        "phone": d.get("phone"),
        "description": d.get("description"),
        "link": d.get("link"),
        "photo_id": d.get("photo_id"),
        "names": d.get("names") or [],
    }


def attach_to_dict(att: Any) -> dict[str, Any]:
    d = _dump(att) or {}
    kind = type(att).__name__
    d["_kind"] = kind
    return d


def _reply_to_id(msg: Any, d: dict[str, Any]) -> int | None:
    msg_type = d.get("type") or getattr(msg, "type", None)
    if str(msg_type).upper() == "REPLY":
        return d.get("prev_message_id") or getattr(msg, "prev_message_id", None)
    return None


def message_to_dict(msg: Any) -> dict[str, Any]:
    d = _dump(msg) or {}
    out = {
        "id": d.get("id"),
        "chat_id": d.get("chat_id"),
        "sender": d.get("sender"),
        "text": d.get("text"),
        "time": d.get("time"),
        "type": str(d.get("type")) if d.get("type") is not None else None,
        "reply_to_id": _reply_to_id(msg, d),
    }
    attaches = d.get("attaches") or getattr(msg, "attaches", None) or []
    if attaches:
        out["attaches"] = [
            attach_to_dict(a) if not isinstance(a, dict) else a for a in attaches
        ]
    return out


def post_to_dict(msg: Any) -> dict[str, Any]:
    base = message_to_dict(msg)
    d = _dump(msg) or {}
    if d.get("reaction_info") is not None:
        base["reaction_info"] = d["reaction_info"]
    if d.get("stats") is not None:
        base["stats"] = d["stats"]
    return base
