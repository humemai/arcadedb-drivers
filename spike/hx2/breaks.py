"""What code written against the httpx-based driver does on the httpx2-based one.

Run with the ported driver installed and `httpx` and `respx` installed beside it, as they are in an
application that used them. Prints observed behaviour only; nothing here is timed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import httpx2
import respx
from arcadedb_driver import ArcadeDBServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    agents: list[str] = []

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Handler.agents.append(self.headers.get("User-Agent", ""))
        body = b'{"result":[{"n":1}],"limit":-1,"returned":1,"truncated":false}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
LIVE = f"http://127.0.0.1:{server.server_address[1]}"
DEAD = "http://127.0.0.1:9"


def query(base_url: str = LIVE, call: dict[str, object] | None = None, **options: object) -> str:
    with ArcadeDBServer(base_url=base_url, **options) as srv:  # type: ignore[arg-type]
        return str(srv.db("db").query(language="sql", command="SELECT 1", **(call or {})).result)  # type: ignore[arg-type]


def except_httpx(transport: str) -> str:
    try:
        query(DEAD, transport=transport)
    except httpx.HTTPError as err:
        return f"caught by except httpx.HTTPError: {type(err)}"
    except Exception as err:
        return f"NOT caught by except httpx.HTTPError; raised {type(err).__module__}.{type(err).__name__}"
    return "no error"


def isinstance_raw() -> str:
    with ArcadeDBServer(base_url=LIVE) as srv:
        client = srv.raw.get_httpx_client()
        return f"isinstance(client, httpx.Client) = {isinstance(client, httpx.Client)}; type {type(client).__module__}"


def set_raw_client() -> str:
    with ArcadeDBServer(base_url=LIVE) as srv:
        srv.raw.set_httpx_client(httpx.Client(base_url=LIVE))
        return str(srv.db("db").query(language="sql", command="SELECT 1").result)


def respx_mock() -> str:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{DEAD}/api/v1/query/db").respond(200, json={"result": [{"mocked": True}]})
        try:
            rows = query(DEAD)
        except Exception as err:
            return f"route called: {route.called}; the request went to the network: {type(err).__name__}"
        return f"route called: {route.called}; rows {rows}"


def user_agent() -> str:
    Handler.agents.clear()
    query()
    return Handler.agents[0]


CASES: list[tuple[str, Callable[[], str]]] = [
    ("except httpx.HTTPError, default transport", lambda: except_httpx("httpx")),
    ("except httpx.HTTPError, transport=http.client", lambda: except_httpx("http.client")),
    ("constructor timeout=httpx.Timeout(5.0)", lambda: query(timeout=httpx.Timeout(5.0))),
    ("same, transport=http.client", lambda: query(timeout=httpx.Timeout(5.0), transport="http.client")),
    ("per-call timeout=httpx.Timeout(5.0)", lambda: query(call={"timeout": httpx.Timeout(5.0)})),
    ("per-call timeout=httpx.USE_CLIENT_DEFAULT", lambda: query(call={"timeout": httpx.USE_CLIENT_DEFAULT})),
    ("httpx_args transport=httpx.HTTPTransport()", lambda: query(httpx_args={"transport": httpx.HTTPTransport()})),
    ("httpx_args limits=httpx.Limits()", lambda: query(httpx_args={"limits": httpx.Limits(max_connections=5)})),
    (
        "httpx_args transport=httpx.MockTransport",
        lambda: query(
            httpx_args={"transport": httpx.MockTransport(lambda r: httpx.Response(200, json={"result": [{"m": 1}]}))}
        ),
    ),
    ("raw.get_httpx_client() type", isinstance_raw),
    ("raw.set_httpx_client(httpx.Client())", set_raw_client),
    ("respx.mock() around a driver call", respx_mock),
    ("User-Agent sent", user_agent),
]

for name, case in CASES:
    try:
        outcome = case()
    except Exception as err:
        outcome = f"raised {type(err).__module__}.{type(err).__name__}: {str(err)[:160]}"
    print(f"{name} -> {outcome}")
print(f"httpx2 {httpx2.__version__}, httpx {httpx.__version__}")
server.shutdown()
