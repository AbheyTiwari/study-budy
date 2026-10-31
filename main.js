const { app, BrowserWindow, Tray, Menu, ipcMain, desktopCapturer, nativeImage, screen } = require('electron');
const path = require('path');
const fs   = require('fs');
const os   = require('os');
const { WebSocketServer } = require('ws');
const Groq = require('groq-sdk');

// ── paths ─────────────────────────────────────────────────────────────────────
const DATA_DIR    = path.join(os.homedir(), '.study_buddy');
const TASKS_FILE  = path.join(DATA_DIR, 'tasks.json');
const CONFIG_FILE = path.join(DATA_DIR, 'config.json');
const LOG_FILE    = path.join(DATA_DIR, 'log.jsonl');
fs.mkdirSync(DATA_DIR, { recursive: true });

// ── state ─────────────────────────────────────────────────────────────────────
let petWin    = null;   // the roaming avatar window
let todoWin   = null;   // small task panel (shows on click)
let setupWin  = null;
let tray      = null;
let groq      = null;
let checkTimer= null;
let paused    = false;
let wsClients = new Set();
const CHECK_MS = 15 * 60 * 1000;
const WS_PORT  = 7432;

// ── config / tasks ────────────────────────────────────────────────────────────
function loadConfig() {
  try { return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8')); } catch { return {}; }
}
function saveConfig(c) { fs.writeFileSync(CONFIG_FILE, JSON.stringify(c, null, 2)); }

function loadTasks() {
  const today = new Date().toISOString().slice(0, 10);
  try {
    return JSON.parse(fs.readFileSync(TASKS_FILE, 'utf8')).map(t => ({
      ...t,
      done: t.addedDate === today ? t.done : false,  // daily reset
      addedDate: t.addedDate || today
    }));
  } catch { return []; }
}
function saveTasks(t) { fs.writeFileSync(TASKS_FILE, JSON.stringify(t, null, 2)); }
function allDone() { const t = loadTasks(); return t.length > 0 && t.every(x => x.done); }

function logEvent(o) {
  fs.appendFileSync(LOG_FILE, JSON.stringify({ ...o, ts: new Date().toISOString() }) + '\n');
}

// ── WebSocket server ──────────────────────────────────────────────────────────
function startWsServer() {
  const wss = new WebSocketServer({ host: '127.0.0.1', port: WS_PORT });
  wss.on('connection', ws => {
    wsClients.add(ws);
    ws.on('close', () => wsClients.delete(ws));
    ws.on('error', () => wsClients.delete(ws));
  });
}
function broadcastCloseTab(hint = '') {
  const msg = JSON.stringify({ action: 'close_tab', hint });
  wsClients.forEach(c => { try { c.send(msg); } catch {} });
}

// ── screenshot ────────────────────────────────────────────────────────────────
async function screenshot() {
  const srcs = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 1280, height: 720 } });
  return srcs[0]?.thumbnail.toJPEG(55).toString('base64') ?? null;
}

// ── Groq vision ───────────────────────────────────────────────────────────────
const SYS = `You are StudyBuddy-Bot. The user is preparing GATE DA/MA 2027.
GATE material: Linear Algebra, Calculus, Probability, Statistics, DSA, ML, AI, Discrete Math, Real Analysis, lectures, PDFs, coding/math practice, GATE portals, question banks.
Classify the screenshot as one of three labels:
STUDYING   — GATE-relevant content clearly visible
DISTRACTED — gaming, entertainment, social media, unrelated browsing (HIGH CONFIDENCE only)
UNCERTAIN  — ambiguous, blank screen, IDE without clear GATE context
Return exactly one JSON line, nothing else:
{"verdict":"STUDYING","reason":"<10 words"}
{"verdict":"DISTRACTED","reason":"<10 words","close_hint":"<title or url fragment>"}
{"verdict":"UNCERTAIN","reason":"<10 words"}`;

async function askGroq(b64) {
  if (!groq) return { verdict: 'UNCERTAIN', reason: 'no key' };
  try {
    const r = await groq.chat.completions.create({
      model: 'meta-llama/llama-4-scout-17b-16e-instruct',
      max_tokens: 120,
      messages: [
        { role: 'system', content: SYS },
        { role: 'user', content: [
          { type: 'image_url', image_url: { url: `data:image/jpeg;base64,${b64}` } },
          { type: 'text', text: 'Classify. One JSON line only.' }
        ]}
      ]
    });
    const raw = r.choices[0].message.content.trim();
    const m = raw.match(/\{.*\}/);
    return m ? JSON.parse(m[0]) : { verdict: 'UNCERTAIN', reason: 'parse fail' };
  } catch(e) {
    logEvent({ event: 'groq_error', err: e.message });
    return { verdict: 'UNCERTAIN', reason: 'api error' };
  }
}

// ── checker ───────────────────────────────────────────────────────────────────
async function runCheck() {
  if (paused) return;
  if (allDone()) {
    petWin?.webContents.send('mood', 'sleeping');
    logEvent({ event: 'skip', reason: 'all done' });
    return;
  }
  const b64 = await screenshot();
  if (!b64) return;
  const res = await askGroq(b64);
  logEvent({ event: 'check', verdict: res.verdict, reason: res.reason });

  if (res.verdict === 'DISTRACTED') {
    broadcastCloseTab(res.close_hint || '');
    petWin?.webContents.send('mood', 'angry');
    petWin?.webContents.send('scold', loadTasks().filter(t => !t.done).map(t => t.text));
  } else if (res.verdict === 'STUDYING') {
    petWin?.webContents.send('mood', 'happy');
  } else {
    petWin?.webContents.send('mood', 'idle');
  }
}

// ── pet window (the avatar) ───────────────────────────────────────────────────
function createPetWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  petWin = new BrowserWindow({
    width: 120, height: 160,
    x: width - 160,
    y: height - 200,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    hasShadow: false,
    webPreferences: { contextIsolation: false, nodeIntegration: true }
  });
  petWin.loadFile(path.join(__dirname, 'renderer', 'pet.html'));
  petWin.setIgnoreMouseEvents(false);
  petWin.on('closed', () => { petWin = null; });
}

// ── todo panel ────────────────────────────────────────────────────────────────
function toggleTodoPanel() {
  if (todoWin && !todoWin.isDestroyed()) {
    todoWin.close();
    todoWin = null;
    return;
  }
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  todoWin = new BrowserWindow({
    width: 340, height: 500,
    x: width - 360,
    y: height - 540,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    transparent: false,
    webPreferences: { contextIsolation: false, nodeIntegration: true }
  });
  todoWin.loadFile(path.join(__dirname, 'renderer', 'todo.html'));
  todoWin.on('closed', () => { todoWin = null; });
}

// ── setup window ──────────────────────────────────────────────────────────────
function createSetupWindow(cb) {
  setupWin = new BrowserWindow({
    width: 480, height: 340,
    frame: false, resizable: false, alwaysOnTop: true,
    webPreferences: { contextIsolation: false, nodeIntegration: true }
  });
  setupWin.loadFile(path.join(__dirname, 'renderer', 'setup.html'));
  ipcMain.once('submit-api-key', (_, key) => {
    const cfg = loadConfig(); cfg.api_key = key; saveConfig(cfg);
    groq = new Groq({ apiKey: key });
    setupWin?.close(); cb();
  });
}

// ── tray ──────────────────────────────────────────────────────────────────────
function createTray() {
  // 16×16 red square icon (minimal — works on all Windows versions)
  const img = nativeImage.createEmpty();
  tray = new Tray(img);
  tray.setToolTip('Study Buddy');
  const menu = Menu.buildFromTemplate([
    { label: '📋 Tasks',      click: toggleTodoPanel },
    { label: '🔍 Check Now', click: runCheck },
    { label: '⏸  Pause 30m', click: () => {
        paused = true;
        setTimeout(() => { paused = false; petWin?.webContents.send('mood','idle'); }, 30*60*1000);
        petWin?.webContents.send('mood', 'sleeping');
        logEvent({ event: 'paused', mins: 30 });
      }
    },
    { type: 'separator' },
    { label: 'Quit', click: () => app.exit(0) }
  ]);
  tray.setContextMenu(menu);
  tray.on('click', toggleTodoPanel);
}

// ── IPC ───────────────────────────────────────────────────────────────────────
ipcMain.handle('load-tasks',    ()      => loadTasks());
ipcMain.handle('save-tasks',    (_, t)  => saveTasks(t));
ipcMain.handle('check-now',     ()      => runCheck());
ipcMain.handle('toggle-todo',   ()      => toggleTodoPanel());
ipcMain.handle('close-todo',    ()      => { todoWin?.close(); });
ipcMain.handle('move-pet',      (_, x, y) => petWin?.setPosition(x, y));
ipcMain.handle('load-log', () => {
  try { return fs.readFileSync(LOG_FILE, 'utf8').trim().split('\n').slice(-40).join('\n'); }
  catch { return ''; }
});

// ── boot ──────────────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  const cfg = loadConfig();
  createPetWindow();
  createTray();
  startWsServer();

  const go = () => {
    checkTimer = setInterval(runCheck, CHECK_MS);
    petWin?.webContents.send('mood', 'idle');
  };

  if (cfg.api_key) { groq = new Groq({ apiKey: cfg.api_key }); go(); }
  else createSetupWindow(go);
});

app.on('window-all-closed', e => e.preventDefault());
