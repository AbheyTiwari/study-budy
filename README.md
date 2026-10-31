# Study Buddy 🤖 — Desktop Pet Edition

A tiny robot that lives on your desktop, walks around, and forces you to study for GATE DA/MA.

## What it does

- **Roams your desktop** — walks left and right, pauses, looks around
- **Talks to you** — random study encouragement every few minutes  
- **Every 15 min** — takes a screenshot, asks Groq AI if you're studying
- **If studying** — goes star-eyed and celebrates ★
- **If distracted** — stomps over, goes angry, closes the tab, scolds you with your own pending tasks
- **All tasks done** — falls asleep with zzz floating up
- **Click the robot** — opens your todo panel

## Setup (build via GitHub Actions — free)

1. Push this folder to a public GitHub repo
2. Go to Actions tab → the build runs automatically (~3 min)
3. Download `StudyBuddy-Windows.zip` from Artifacts → extract → run the `.exe`
4. On first launch: paste your free Groq key (console.groq.com → API Keys → Create)

## Load the browser extension

Chrome/Edge → `chrome://extensions` → Developer mode ON → Load unpacked → pick the `extension/` folder

## Files

```
main.js              — Electron main process (checker, WebSocket, windows)
renderer/pet.html    — The walking animated robot avatar
renderer/todo.html   — Task panel (opens on click)
renderer/setup.html  — First-run API key screen
extension/           — Chrome/Edge extension (closes distraction tabs)
```
