"""Points `respx` at httpx2's transport.

`respx` patches `httpcore` by default, which the driver no longer uses, so an unconfigured mock would
let every request go to the network. `pytest-httpx2` (by the `respx` author) registers an
`httpcore2` mocker; making it the default keeps every `@respx.mock` test as written. The mocked
responses stay `httpx.Response` objects, because that is the only response type `respx` accepts, so
`httpx` remains a test dependency (never a runtime one: `test_isolation.py` and CI check that).
"""

import pytest_httpx2  # noqa: F401  (importing it registers the "httpcore2" mocker)
import respx.mocks

respx.mocks.DEFAULT_MOCKER = "httpcore2"
