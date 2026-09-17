'use strict'

const fs = require('node:fs')
const path = require('node:path')

const desktopRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(desktopRoot, '../..')
const webDist = path.join(repoRoot, 'web', 'dist')
const stagedWeb = path.join(desktopRoot, 'resources', 'web-dist')
const backendDir = path.join(desktopRoot, 'resources', 'backend')
const backendName = process.platform === 'win32' ? 'sprite-studio-api.exe' : 'sprite-studio-api'
const backendTarget = path.join(backendDir, backendName)

if (!fs.existsSync(path.join(webDist, 'index.html'))) {
  throw new Error('web/dist/index.html is missing. Run "npm run build:web" first.')
}

const configuredBackend = process.env.SPRITE_STUDIO_BACKEND_BIN
  ? path.resolve(process.env.SPRITE_STUDIO_BACKEND_BIN)
  : backendTarget
if (!fs.existsSync(configuredBackend)) {
  throw new Error(`Backend artifact is missing: ${configuredBackend}\nBuild a PyInstaller backend and set SPRITE_STUDIO_BACKEND_BIN, or place it at ${backendTarget}.`)
}

fs.rmSync(stagedWeb, { recursive: true, force: true })
fs.cpSync(webDist, stagedWeb, { recursive: true })
fs.mkdirSync(backendDir, { recursive: true })
if (path.resolve(configuredBackend) !== path.resolve(backendTarget)) fs.copyFileSync(configuredBackend, backendTarget)
if (process.platform !== 'win32') fs.chmodSync(backendTarget, 0o755)
console.log(`Staged React build: ${stagedWeb}`)
console.log(`Staged FastAPI backend: ${backendTarget}`)
