"""The per-call `timeout` argument shared by the facades.

`USE_CLIENT_DEFAULT` is httpx2's own sentinel: passing it to a request keeps the timeout of the
client the request goes through, which is exactly what a call that never mentions `timeout` did
before the argument existed. A `float`, an `httpx2.Timeout` or `None` replaces the client's timeout
for that one call (`None` meaning no timeout, as everywhere in httpx2).

httpx2 does not export the sentinel's class, so the type is imported from its private module for the
type checker only and rebuilt from the sentinel at run time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2

if TYPE_CHECKING:
    from httpx2._client import UseClientDefault
else:
    UseClientDefault = type(httpx2.USE_CLIENT_DEFAULT)

USE_CLIENT_DEFAULT = httpx2.USE_CLIENT_DEFAULT

CallTimeout = float | httpx2.Timeout | None | UseClientDefault

__all__ = ["USE_CLIENT_DEFAULT", "CallTimeout", "UseClientDefault"]
