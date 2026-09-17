# FastAPI desktop backend artifact

The Electron packaging scripts expect a platform-native executable here:

- Windows: `sprite-studio-api.exe`
- macOS/Linux: `sprite-studio-api`

Build the FastAPI entry point with the project dependencies (for example, a
PyInstaller `--onedir` or `--onefile` build), then either copy the artifact to
this directory or set `SPRITE_STUDIO_BACKEND_BIN` to its path before running
`npm run make`.

The executable must accept `--host`, `--port`, and `--port 0`, and must print a
line matching `listening on http://127.0.0.1:<port>`. The desktop shell uses that
line only as a startup handshake, then verifies `/api/health` before opening
the window. Runtime run data is stored in the Electron user-data directory.
