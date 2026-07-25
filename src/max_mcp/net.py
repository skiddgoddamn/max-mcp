import os

# System/VPN proxies leak into this process via these vars; the websockets
# client honors them and routes the MAX connection through the proxy, which
# silently times out the WS handshake even though oneme.ru is directly
# reachable. MAX's own servers are meant to be reached directly.
_PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "WS_PROXY",
    "WSS_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "ws_proxy",
    "wss_proxy",
)


def configure_proxy() -> str | None:
    """Decide how MAX traffic is proxied and return the proxy URL (or None).

    Default: strip any ambient HTTP(S)/ALL proxy from this process so the
    WebSocket/TCP transport talks to oneme.ru directly. Set ``MAX_MCP_PROXY`` to
    route MAX through a specific proxy instead (e.g. if MAX is geo-blocked).
    """
    explicit = os.environ.get("MAX_MCP_PROXY")
    if explicit:
        return explicit
    for var in _PROXY_VARS:
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    return None
