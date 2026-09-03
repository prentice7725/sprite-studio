# SPDX-License-Identifier: Apache-2.0
"""One module per ENDPOINTS.md domain section. A router parses the request,
calls exactly one `studio/backend/*` function, and shapes the response with a
`studio.api.contracts` model — no engine calls, no file I/O of its own beyond
what `assets.py` needs to stream a file a backend service already resolved."""
