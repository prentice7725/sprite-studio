# SPDX-License-Identifier: Apache-2.0
"""FastAPI surface for Sprite Studio — the React migration target.

This package is a thin HTTP boundary in front of the existing, UI-agnostic
`studio/backend/*` services. It must never talk to `sprite_studio/*` (the engine)
directly, and it must never do file I/O of its own beyond serving files a
backend service already resolved — see ``contracts.py`` for the full request/
response contract and ``ENDPOINTS.md`` (next to this file) for the
endpoint-to-backend-function map.
"""
