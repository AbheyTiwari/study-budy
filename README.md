# Study Buddy 🤖

A lightweight Windows study enforcer for GATE DA/MA prep.

Every 15 minutes it takes a screenshot, asks Claude if you're studying, and if you're not — it closes the tab and yells at you.

## Requirements

- Windows 10/11
- Python 3.11+
- An Anthropic API key (get one at console.anthropic.com — costs ~₹0.10–0.30 per day at typical usage)

## Quick Start

### Step 1 — Install and build
```
pip install -r requirements.txt
python create_icon.py
build.bat
```
This produces `dist\StudyBuddy.exe`.

### Step 2 — Load browser extension
1. Open Chrome or Edge → go to `chrome://extensions` (or `edge://extensions`)
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder from this directory

### Step 3 — Run
Double-click `dist\StudyBuddy.exe`.  
On first run it asks for your Anthropic API key — paste it in. It's saved to `%USERPROFILE%\.study_buddy\config.json` on your machine only.

---

## How it works

```
Every 15 minutes
   ├── Capture screenshot (mss — fast, low RAM)
   ├── Send to Claude claude-opus-4-5 vision API
   │     └── Verdict: STUDYING / DISTRACTED / UNCERTAIN
   └── If DISTRACTED:
         ├── Tell browser extension (WebSocket on 127.0.0.1:7432) → close active tab
         ├── Fallback: send WM_CLOSE to foreground window
         └── Show full-screen "STOP. GET BACK TO STUDYING." overlay
```

## Resource usage

| Component | Typical |
|-----------|---------|
| RAM | ~50–90 MB |
| CPU idle | <1% |
| CPU at check | brief spike, ~2s |
| API calls | 1 per 15 min (~96/day) |

Well under your 400 MB RAM ceiling.

## Todo list

- Tasks are stored in `%USERPROFILE%\.study_buddy\tasks.json`
- Mark tasks complete with the checkbox — once all are done, buddy shuts up for the day
- Add tasks from the main window or edit the JSON directly

## Pause

Click **Pause 30 min** in the app or tray menu — useful for legitimate breaks or when you need to do something real on your PC.

## Log

Click **View Log** to see the last 30 check events: what verdict Claude gave and when enforcement was triggered.

---

## Build from source (alternative)
```
pyinstaller --onefile --windowed --name StudyBuddy study_buddy.py
```

## Troubleshooting

**"API key required"** — Make sure your key is in `%USERPROFILE%\.study_buddy\config.json`  
**Tab not closing** — Make sure the browser extension is loaded and enabled  
**Always UNCERTAIN** — Screenshot quality is fine; Claude may need the hint. Try running a check manually.  
**"No module named mss"** — Run `pip install mss` before building  
