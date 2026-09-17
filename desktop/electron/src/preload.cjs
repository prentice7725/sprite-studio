'use strict'

// Keep the renderer web-only for now. Native APIs belong behind a deliberately
// narrow preload bridge when the desktop shell needs them; React must continue
// to use the FastAPI HTTP/WebSocket contract for all Studio operations.
