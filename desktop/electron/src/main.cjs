'use strict'

const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { app, BrowserWindow, dialog } = require('electron')

if (require('electron-squirrel-startup')) {
  app.quit()
}

const repoRoot = path.resolve(__dirname, '../../..')
let mainWindow = null
let backendProcess = null
let backendUrl = null

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

function backendWebDist() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'web-dist')
    : path.join(repoRoot, 'web', 'dist')
}

function developmentPython() {
  if (process.env.SPRITE_STUDIO_PYTHON) return process.env.SPRITE_STUDIO_PYTHON
  const venvPython = process.platform === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python')
  return fs.existsSync(venvPython) ? venvPython : 'python'
}

function backendLaunchSpec() {
  if (!app.isPackaged) {
    return {
      command: developmentPython(),
      args: ['-u', '-m', 'studio.api.main', '--host', '127.0.0.1', '--port', '0'],
      cwd: repoRoot,
    }
  }

  const binaryName = process.platform === 'win32' ? 'sprite-studio-api.exe' : 'sprite-studio-api'
  const configured = process.env.SPRITE_STUDIO_BACKEND_BIN
  const command = configured ? path.resolve(configured) : path.join(process.resourcesPath, 'backend', binaryName)
  if (!fs.existsSync(command)) {
    throw new Error(`Packaged FastAPI backend was not found: ${command}`)
  }
  return { command, args: ['--host', '127.0.0.1', '--port', '0'], cwd: process.resourcesPath }
}

function backendEnvironment() {
  const userData = app.getPath('userData')
  const packagedRuns = path.join(userData, 'runs')
  return {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    SPRITE_STUDIO_API_HOST: '127.0.0.1',
    SPRITE_STUDIO_API_PORT: '0',
    SPRITE_STUDIO_WEB_DIST: backendWebDist(),
    ...(app.isPackaged ? {
      SPRITE_STUDIO_RUNS_ROOT: process.env.SPRITE_STUDIO_RUNS_ROOT || packagedRuns,
      SPRITE_STUDIO_STATIC_ROOT: process.env.SPRITE_STUDIO_STATIC_ROOT || path.join(userData, 'static'),
      SPRITE_STUDIO_UPLOADS_ROOT: process.env.SPRITE_STUDIO_UPLOADS_ROOT || path.join(userData, 'uploads'),
    } : {}),
  }
}

function waitForListeningPort(child) {
  return new Promise((resolve, reject) => {
    let settled = false
    let output = ''
    const finish = (error, port) => {
      if (settled) return
      settled = true
      if (error) reject(error)
      else resolve(port)
    }
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      output += chunk
      process.stdout.write(`[sprite-studio-api] ${chunk}`)
      const match = output.match(/listening on https?:\/\/127\.0\.0\.1:(\d+)/i) || output.match(/Uvicorn running on https?:\/\/127\.0\.0\.1:(\d+)/i)
      if (match) finish(null, Number(match[1]))
    })
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk) => process.stderr.write(`[sprite-studio-api] ${chunk}`))
    child.once('error', (error) => finish(error))
    child.once('exit', (code, signal) => {
      if (!settled) finish(new Error(`FastAPI exited before announcing a port (code=${code}, signal=${signal || 'none'})`))
    })
  })
}

function requestHealth(url) {
  return new Promise((resolve) => {
    const request = http.get(`${url}/api/health`, (response) => {
      response.resume()
      resolve(response.statusCode === 200)
    })
    request.setTimeout(1500, () => {
      request.destroy()
      resolve(false)
    })
    request.on('error', () => resolve(false))
  })
}

async function waitForHealth(url, child) {
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error('FastAPI exited while waiting for its health endpoint')
    if (await requestHealth(url)) return
    await delay(200)
  }
  throw new Error(`FastAPI health check timed out: ${url}/api/health`)
}

async function startBackend() {
  const spec = backendLaunchSpec()
  backendProcess = spawn(spec.command, spec.args, {
    cwd: spec.cwd,
    env: backendEnvironment(),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const port = await waitForListeningPort(backendProcess)
  const url = `http://127.0.0.1:${port}`
  await waitForHealth(url, backendProcess)
  return url
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) return
  backendProcess.kill()
  backendProcess = null
}

function sameOrigin(url) {
  if (!backendUrl) return false
  try {
    return new URL(url).origin === new URL(backendUrl).origin
  } catch {
    return false
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 960,
    minHeight: 700,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => ({ action: sameOrigin(url) ? 'allow' : 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!sameOrigin(url)) event.preventDefault()
  })
  mainWindow.once('ready-to-show', () => mainWindow.show())
  return mainWindow.loadURL(backendUrl)
}

async function launch() {
  try {
    backendUrl = await startBackend()
    await createWindow()
  } catch (error) {
    stopBackend()
    const message = error instanceof Error ? error.message : String(error)
    dialog.showErrorBox('Sprite Studio could not start', `${message}\n\nCheck the Python environment or packaged backend artifact, then retry.`)
    app.quit()
  }
}

const hasLock = app.requestSingleInstanceLock()
if (!hasLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })
  app.whenReady().then(launch)
  app.on('activate', () => {
    if (mainWindow === null && backendUrl) void createWindow()
  })
  app.on('before-quit', stopBackend)
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
}
