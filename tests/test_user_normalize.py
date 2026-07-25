from max_mcp.normalize import _display_name, user_to_dict


def test_display_name_prefers_full_name():
    assert _display_name([{"name": "Ivan Petrov", "first_name": "Ivan"}]) == "Ivan Petrov"


def test_display_name_falls_back_to_first_last():
    assert _display_name([{"first_name": "Ivan", "last_name": "Petrov"}]) == "Ivan Petrov"


def test_display_name_first_only():
    assert _display_name([{"first_name": "Ann"}]) == "Ann"


def test_display_name_none_when_empty():
    assert _display_name([]) is None
    assert _display_name(None) is None


def test_user_to_dict_shape():
    class U:
        def model_dump(self, **_):
            return {"id": 42, "names": [{"name": "Ann"}], "phone": 79990001122}

    d = user_to_dict(U())
    assert d == {
        "id": 42,
        "name": "Ann",
        "phone": 79990001122,
        "description": None,
        "link": None,
        "photo_id": None,
        "names": [{"name": "Ann"}],
    }


def test_user_to_dict_none():
    assert user_to_dict(None) is None
