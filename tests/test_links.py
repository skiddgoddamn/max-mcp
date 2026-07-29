import pytest

from max_mcp.tools.links import _extract, _link_slug, _name_from


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://max.ru/id2465215235_biz", "id2465215235_biz"),
        ("max.ru/id2465215235_biz", "id2465215235_biz"),  # scheme-less host stripped
        ("id2465215235_biz", "id2465215235_biz"),
        ("https://max.ru/u/f9LHodD0cOK9lyI-TyIQ", "u/f9LHodD0cOK9lyI-TyIQ"),
        ("max.ru/u/TOKEN?utm=1#frag", "u/TOKEN"),
        ("u/TOKEN", "u/TOKEN"),  # bare path, u/ prefix kept (not a host)
        ("  https://oneme.ru/salon_kirov  ", "salon_kirov"),
    ],
)
def test_link_slug(raw, expected):
    assert _link_slug(raw) == expected


def test_link_slug_rejects_empty():
    for bad in ("", "   ", "https://"):
        with pytest.raises(ValueError):
            _link_slug(bad)


def test_extract_chat():
    payload = {
        "chat": {
            "id": -70622366624393,
            "type": "CHANNEL",
            "access": "PUBLIC",
            "title": "TERVE",
            "link": "https://max.ru/id2465215235_biz",
            "participantsCount": 108,
        }
    }
    r = _extract(payload, my_id=34690964, link="max.ru/id2465215235_biz", slug="id2465215235_biz")
    assert r["kind"] == "chat"
    assert r["chat_id"] == -70622366624393
    assert r["chat_type"] == "CHANNEL"
    assert r["participants_count"] == 108
    assert r["title"] == "TERVE"


def test_extract_user_derives_dialog_id():
    payload = {"contact": {"id": 111, "names": [{"firstName": "Ann", "lastName": "P"}]}}
    r = _extract(payload, my_id=222, link="max.ru/u/x", slug="u/x")
    assert r["kind"] == "user"
    assert r["user_id"] == 111
    assert r["name"] == "Ann P"
    assert r["chat_id"] == 222 ^ 111  # 1:1 dialog id


def test_extract_unknown_keeps_raw():
    r = _extract({"weird": {}}, my_id=1, link="x", slug="x")
    assert r["kind"] == "unknown"
    assert r["raw_keys"] == ["weird"]


def test_name_from_prefers_name_field():
    assert _name_from({"names": [{"name": "Full Name", "firstName": "Full"}]}) == "Full Name"
    assert _name_from({"firstName": "Solo"}) == "Solo"
    assert _name_from({}) is None
