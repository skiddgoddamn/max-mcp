import asyncio

from max_mcp.tools.channels import collect_posts, next_cursor


def _history(total: int, newest_time: int = 10_000):
    """A channel of `total` posts, one second apart, newest first."""
    return [
        {"id": i, "time": newest_time - i, "text": f"post {i}"} for i in range(total)
    ]


def _fetcher(posts):
    """Fake pymax fetch_history: backward page starting at from_time."""
    calls = []

    async def fetch(chat_id: int, backward: int, from_time=None):
        calls.append({"from_time": from_time, "backward": backward})
        page = [p for p in posts if from_time is None or p["time"] <= from_time]
        return page[:backward]

    return fetch, calls


def test_next_cursor_stops_on_short_page():
    assert next_cursor([{"time": 5}], expected=50) is None


def test_next_cursor_survives_missing_time():
    # service events can arrive without a time — subtracting from None used to raise
    assert next_cursor([{"time": None}], expected=1) is None
    assert next_cursor([{"time": 5}], expected=1) == 4


def test_dump_stops_at_max_posts_and_returns_a_usable_cursor():
    posts = _history(500)
    fetch, _ = _fetcher(posts)
    out = asyncio.run(
        collect_posts(fetch, 1, since_time=None, max_posts=120, before_time=None)
    )

    assert out["count"] == 120
    assert out["stopped_reason"] == "max_posts"
    # the cursor is what upstream never returned: without it the caller could
    # not page past max_posts at all
    assert out["next_before_time"] == posts[119]["time"] - 1


def test_before_time_resumes_where_the_previous_call_stopped():
    posts = _history(500)
    fetch, _ = _fetcher(posts)

    first = asyncio.run(
        collect_posts(fetch, 1, since_time=None, max_posts=120, before_time=None)
    )
    second = asyncio.run(
        collect_posts(
            fetch, 1, since_time=None, max_posts=120,
            before_time=first["next_before_time"],
        )
    )

    assert [p["id"] for p in first["posts"]] == list(range(120))
    assert [p["id"] for p in second["posts"]] == list(range(120, 240))
    assert not {p["id"] for p in first["posts"]} & {p["id"] for p in second["posts"]}


def test_exhausted_channel_reports_no_cursor():
    fetch, _ = _fetcher(_history(30))
    out = asyncio.run(
        collect_posts(fetch, 1, since_time=None, max_posts=1000, before_time=None)
    )

    assert out["count"] == 30
    assert out["stopped_reason"] == "exhausted"
    assert out["next_before_time"] is None


def test_since_time_stops_the_walk():
    fetch, _ = _fetcher(_history(500, newest_time=10_000))
    out = asyncio.run(
        collect_posts(fetch, 1, since_time=9_950, max_posts=1000, before_time=None)
    )

    assert out["stopped_reason"] == "since_time"
    assert all(p["time"] >= 9_950 for p in out["posts"])
    assert out["next_before_time"] is None
