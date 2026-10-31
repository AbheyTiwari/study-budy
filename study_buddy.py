"""
Study Buddy — GATE DA/MA enforcer
Runs in system tray. Every 15 min takes a screenshot, asks Claude if you're studying,
closes the distraction and yells at you if not.
Requires: ANTHROPIC_API_KEY env var
"""

import os
import sys
import json
import time
import base64
import ctypes
import threading
import subprocess
import datetime
import tempfile
import io
from pathlib import Path

# ── deps ──────────────────────────────────────────────────────────────────────
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
except ImportError:
    sys.exit("tkinter not found — install Python with tkinter support")

try:
    import pystray
    from pystray import MenuItem as Item
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("pip install pystray pillow")

try:
    import anthropic
except ImportError:
    sys.exit("pip install anthropic")

try:
    import mss
    import mss.tools
except ImportError:
    sys.exit("pip install mss")

# ── config ────────────────────────────────────────────────────────────────────
APP_NAME        = "Study Buddy"
CHECK_INTERVAL  = 15 * 60          # seconds between AI checks
DATA_FILE       = Path.home() / ".study_buddy" / "tasks.json"
LOG_FILE        = Path.home() / ".study_buddy" / "log.jsonl"
WS_PORT         = 7432             # WebSocket port for browser extension

DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

# ── Claude vision ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are StudyBuddy-Bot, a robot whose ONLY job is to keep its user
studying for GATE DA (Data Science & AI) and GATE MA (Mathematics).

The user is preparing for GATE 2027 and needs to study:
- Linear Algebra, Calculus, Probability, Statistics
- Data Science, Machine Learning, AI
- Discrete Math, DSA, Algorithms
- Mathematical reasoning, Matrices, Real Analysis

You will receive a screenshot. Classify it as one of exactly three labels:
STUDYING   — The screen clearly shows GATE-relevant material: lecture slides, PDFs of
             textbooks/notes, coding environments (Python/Jupyter doing math/ML),
             question banks, GATE practice portals, math YouTube lectures,
             handwritten notes on camera, official study resources.
DISTRACTED — Gaming, entertainment videos (non-educational), social media,
             shopping, random browsing unrelated to study, messaging apps used
             recreationally, movie streaming.
UNCERTAIN  — Screen is blank/locked, system settings, ambiguous mix, file manager,
             IDE open but not clearly GATE-related, multiple windows unclear.

Rules:
- Only return DISTRACTED when you are HIGHLY CONFIDENT it is not study-related.
- A coding IDE or terminal by itself → UNCERTAIN (not necessarily distracted).
- YouTube only → DISTRACTED unless it's clearly a lecture/educational video.
- Return a JSON object on ONE line, nothing else:
  {"verdict":"STUDYING","reason":"<10 words max>"}
  {"verdict":"DISTRACTED","reason":"<10 words max>","close_hint":"<window title or url fragment if visible>"}
  {"verdict":"UNCERTAIN","reason":"<10 words max>"}
"""

def capture_screenshot() -> bytes:
    """Capture primary monitor, return JPEG bytes."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]          # primary monitor
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        return buf.getvalue()


def ask_claude(jpg_bytes: bytes) -> dict:
    """Send screenshot to Claude vision, return parsed verdict dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"verdict": "UNCERTAIN", "reason": "no API key set"}

    client = anthropic.Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(jpg_bytes).decode("utf-8")

    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=120,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                },
                {
                    "type": "text",
                    "text": "Classify what this person is doing on their PC right now. "
                            "Reply with exactly one JSON line as instructed."
                }
            ],
        }]
    )

    raw = msg.content[0].text.strip()
    # Extract JSON even if model adds extra text
    import re
    m = re.search(r'\{.*\}', raw)
    if m:
        return json.loads(m.group())
    return {"verdict": "UNCERTAIN", "reason": "parse error"}


# ── window / tab closer ────────────────────────────────────────────────────────
def close_foreground_window():
    """Close the currently focused window (Windows only)."""
    if sys.platform != "win32":
        return
    import ctypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


def close_browser_tab_via_extension(hint: str = ""):
    """Tell browser extension (via WebSocket) to close the active/distraction tab."""
    try:
        import websocket  # websocket-client
        ws = websocket.create_connection(f"ws://127.0.0.1:{WS_PORT}", timeout=2)
        ws.send(json.dumps({"action": "close_tab", "hint": hint}))
        ws.close()
    except Exception:
        # Extension not running or not installed — fall back to closing foreground window
        close_foreground_window()


# ── task persistence ───────────────────────────────────────────────────────────
def load_tasks() -> list:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_tasks(tasks: list):
    DATA_FILE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")


def log_event(event: dict):
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**event, "ts": datetime.datetime.now().isoformat()}) + "\n")


# ── tray icon ──────────────────────────────────────────────────────────────────
def make_tray_icon(color: str = "#4CAF50") -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Simple robot face
    d.ellipse([4, 4, 60, 60], fill=color)
    d.rectangle([16, 22, 26, 32], fill="white")   # left eye
    d.rectangle([38, 22, 48, 32], fill="white")   # right eye
    d.rectangle([20, 42, 44, 48], fill="white")   # mouth
    return img


# ── main app class ────────────────────────────────────────────────────────────
class StudyBuddy:
    def __init__(self):
        self.tasks = load_tasks()
        self.paused = False
        self.running = True
        self.last_check: datetime.datetime | None = None
        self.next_check_time: float = time.monotonic() + CHECK_INTERVAL
        self.lock = threading.Lock()

        # Build UI on main thread
        self._build_todo_window()
        self._build_tray()

        # Start background checker
        self._checker_thread = threading.Thread(target=self._checker_loop, daemon=True)
        self._checker_thread.start()

        # Start WebSocket server for browser extension
        self._ws_thread = threading.Thread(target=self._ws_server_loop, daemon=True)
        self._ws_thread.start()

    # ── todo window ──────────────────────────────────────────────────────────
    def _build_todo_window(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("360x480")
        self.root.resizable(False, True)
        self.root.protocol("WM_DELETE_WINDOW", self._hide_window)
        self.root.configure(bg="#1a1a2e")

        # Header
        hdr = tk.Frame(self.root, bg="#16213e", pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🤖 Study Buddy", font=("Segoe UI", 14, "bold"),
                 bg="#16213e", fg="#e94560").pack(side="left", padx=12)
        tk.Label(hdr, text="GATE DA/MA", font=("Segoe UI", 9),
                 bg="#16213e", fg="#aaa").pack(side="left")

        # Status bar
        self.status_var = tk.StringVar(value="Watching… next check in 15:00")
        status_bar = tk.Label(self.root, textvariable=self.status_var,
                               font=("Segoe UI", 8), bg="#0f3460", fg="#e2e2e2",
                               anchor="w", padx=8, pady=4)
        status_bar.pack(fill="x")

        # Task list frame
        list_frame = tk.Frame(self.root, bg="#1a1a2e")
        list_frame.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        tk.Label(list_frame, text="Today's Tasks", font=("Segoe UI", 10, "bold"),
                 bg="#1a1a2e", fg="#e2e2e2").pack(anchor="w", pady=(0, 4))

        self.task_frame = tk.Frame(list_frame, bg="#1a1a2e")
        self.task_frame.pack(fill="both", expand=True)
        self._render_tasks()

        # Add task row
        add_frame = tk.Frame(self.root, bg="#1a1a2e", pady=6)
        add_frame.pack(fill="x", padx=10)
        self.new_task_var = tk.StringVar()
        entry = tk.Entry(add_frame, textvariable=self.new_task_var,
                         font=("Segoe UI", 9), bg="#16213e", fg="#e2e2e2",
                         insertbackground="white", relief="flat", bd=4)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self._add_task())
        tk.Button(add_frame, text="+ Add", command=self._add_task,
                  bg="#e94560", fg="white", relief="flat",
                  font=("Segoe UI", 9, "bold"), padx=8).pack(side="left", padx=(4, 0))

        # Buttons
        btn_frame = tk.Frame(self.root, bg="#1a1a2e", pady=6)
        btn_frame.pack(fill="x", padx=10)
        tk.Button(btn_frame, text="Check Now", command=self._manual_check,
                  bg="#0f3460", fg="white", relief="flat",
                  font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        tk.Button(btn_frame, text="Pause 30 min", command=self._pause,
                  bg="#444", fg="white", relief="flat",
                  font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        tk.Button(btn_frame, text="View Log", command=self._view_log,
                  bg="#444", fg="white", relief="flat",
                  font=("Segoe UI", 9)).pack(side="left")

        # Countdown updater
        self._update_countdown()

    def _render_tasks(self):
        for w in self.task_frame.winfo_children():
            w.destroy()

        if not self.tasks:
            tk.Label(self.task_frame, text="No tasks yet. Add one below ↓",
                     font=("Segoe UI", 9, "italic"), bg="#1a1a2e", fg="#666").pack(anchor="w")
            return

        for i, task in enumerate(self.tasks):
            row = tk.Frame(self.task_frame, bg="#1a1a2e")
            row.pack(fill="x", pady=2)

            var = tk.BooleanVar(value=task.get("done", False))

            def on_toggle(idx=i, v=var):
                with self.lock:
                    self.tasks[idx]["done"] = v.get()
                    save_tasks(self.tasks)
                self._check_all_done()

            cb = tk.Checkbutton(row, variable=var, command=on_toggle,
                                bg="#1a1a2e", activebackground="#1a1a2e",
                                selectcolor="#0f3460",
                                fg="#e2e2e2" if not task.get("done") else "#555",
                                activeforeground="#e2e2e2",
                                font=("Segoe UI", 9),
                                text=task["text"],
                                anchor="w", wraplength=260, justify="left")
            cb.pack(side="left", fill="x", expand=True)

            tk.Button(row, text="✕", command=lambda idx=i: self._delete_task(idx),
                      bg="#1a1a2e", fg="#555", relief="flat",
                      font=("Segoe UI", 8), padx=2).pack(side="right")

    def _add_task(self):
        text = self.new_task_var.get().strip()
        if not text:
            return
        with self.lock:
            self.tasks.append({"text": text, "done": False,
                                "added": datetime.date.today().isoformat()})
            save_tasks(self.tasks)
        self.new_task_var.set("")
        self._render_tasks()

    def _delete_task(self, idx: int):
        with self.lock:
            self.tasks.pop(idx)
            save_tasks(self.tasks)
        self._render_tasks()

    def _check_all_done(self):
        with self.lock:
            all_done = all(t.get("done", False) for t in self.tasks) and len(self.tasks) > 0
        if all_done:
            self._show_completion_popup()

    def _show_completion_popup(self):
        popup = tk.Toplevel(self.root)
        popup.title("🎉 Done!")
        popup.configure(bg="#1a1a2e")
        popup.geometry("300x160")
        popup.attributes("-topmost", True)
        tk.Label(popup, text="All tasks done! 🎉\nGood work today.",
                 font=("Segoe UI", 13, "bold"), bg="#1a1a2e", fg="#4CAF50").pack(pady=30)
        tk.Button(popup, text="Close", command=popup.destroy,
                  bg="#0f3460", fg="white", relief="flat").pack()
        log_event({"event": "all_done"})

    def _update_countdown(self):
        remaining = max(0, int(self.next_check_time - time.monotonic()))
        m, s = divmod(remaining, 60)
        if self.paused:
            self.status_var.set("⏸ Paused")
        else:
            self.status_var.set(f"👁 Watching — next check in {m:02d}:{s:02d}")
        self.root.after(1000, self._update_countdown)

    def _hide_window(self):
        self.root.withdraw()

    def _show_window(self, *_):
        self.root.deiconify()
        self.root.lift()
        self._render_tasks()

    def _pause(self):
        self.paused = True
        self.next_check_time = time.monotonic() + 30 * 60
        self.status_var.set("⏸ Paused for 30 min")
        self.root.after(30 * 60 * 1000, self._unpause)
        log_event({"event": "paused", "duration_min": 30})

    def _unpause(self):
        self.paused = False
        self.next_check_time = time.monotonic() + CHECK_INTERVAL
        log_event({"event": "unpaused"})

    def _manual_check(self):
        threading.Thread(target=self._do_check, daemon=True).start()

    def _view_log(self):
        if not LOG_FILE.exists():
            messagebox.showinfo("Log", "No log entries yet.")
            return
        lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")[-30:]
        win = tk.Toplevel(self.root)
        win.title("Recent Log")
        win.configure(bg="#1a1a2e")
        win.geometry("500x400")
        text = tk.Text(win, bg="#0f3460", fg="#e2e2e2",
                       font=("Consolas", 8), wrap="word")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        for line in lines:
            try:
                obj = json.loads(line)
                text.insert("end", f"[{obj.get('ts','')}] {obj.get('event','')} — "
                                   f"{obj.get('verdict','')}{obj.get('reason','')}\n")
            except Exception:
                text.insert("end", line + "\n")
        text.config(state="disabled")

    # ── tray ──────────────────────────────────────────────────────────────────
    def _build_tray(self):
        icon_img = make_tray_icon()
        menu = pystray.Menu(
            Item("Open Study Buddy", self._show_window, default=True),
            Item("Check Now", lambda: threading.Thread(target=self._do_check, daemon=True).start()),
            Item("Pause 30 min", lambda: self.root.after(0, self._pause)),
            pystray.Menu.SEPARATOR,
            Item("Quit", self._quit),
        )
        self.tray = pystray.Icon(APP_NAME, icon_img, APP_NAME, menu)

    def _quit(self, *_):
        self.running = False
        self.tray.stop()
        self.root.after(0, self.root.destroy)

    # ── checker loop ──────────────────────────────────────────────────────────
    def _checker_loop(self):
        while self.running:
            time.sleep(1)
            if self.paused:
                continue
            if time.monotonic() >= self.next_check_time:
                self.next_check_time = time.monotonic() + CHECK_INTERVAL
                self._do_check()

    def _do_check(self):
        try:
            jpg = capture_screenshot()
            result = ask_claude(jpg)
            verdict = result.get("verdict", "UNCERTAIN")
            reason  = result.get("reason", "")
            hint    = result.get("close_hint", "")

            log_event({"event": "check", "verdict": verdict, "reason": reason})

            if verdict == "DISTRACTED":
                self._enforce(hint)
        except Exception as e:
            log_event({"event": "check_error", "error": str(e)})

    def _enforce(self, hint: str):
        # Close the distraction
        close_browser_tab_via_extension(hint)

        # Show forceful overlay on main thread
        self.root.after(0, lambda: self._show_scold_overlay())

    def _show_scold_overlay(self):
        overlay = tk.Toplevel(self.root)
        overlay.attributes("-fullscreen", False)
        overlay.attributes("-topmost", True)
        overlay.overrideredirect(True)

        # Position: center of screen, large
        sw = overlay.winfo_screenwidth()
        sh = overlay.winfo_screenheight()
        w, h = 520, 280
        x = (sw - w) // 2
        y = (sh - h) // 2
        overlay.geometry(f"{w}x{h}+{x}+{y}")
        overlay.configure(bg="#1a0000")

        tk.Label(overlay, text="🤖 STOP.",
                 font=("Segoe UI", 36, "bold"), bg="#1a0000", fg="#e94560").pack(pady=(30, 4))
        tk.Label(overlay, text="That is NOT GATE material.\nGet back to studying. NOW.",
                 font=("Segoe UI", 14), bg="#1a0000", fg="#ffcccc",
                 justify="center").pack(pady=4)

        # Show pending tasks
        with self.lock:
            pending = [t["text"] for t in self.tasks if not t.get("done")]
        if pending:
            preview = "\n".join(f"  • {t}" for t in pending[:3])
            if len(pending) > 3:
                preview += f"\n  … and {len(pending)-3} more"
            tk.Label(overlay, text=f"You still need to do:\n{preview}",
                     font=("Segoe UI", 10), bg="#1a0000", fg="#ffaaaa",
                     justify="left").pack(pady=8)

        # Auto-close after 8s; or user clicks OK
        def close_overlay():
            overlay.destroy()

        tk.Button(overlay, text="OK I'M GOING BACK",
                  command=close_overlay,
                  bg="#e94560", fg="white", relief="flat",
                  font=("Segoe UI", 11, "bold"), padx=12, pady=6).pack(pady=8)

        overlay.after(8000, lambda: overlay.destroy() if overlay.winfo_exists() else None)

        log_event({"event": "enforced"})

    # ── WebSocket server (for browser extension) ───────────────────────────────
    def _ws_server_loop(self):
        """Tiny async WebSocket server so the browser extension can receive commands."""
        try:
            import asyncio
            import websockets

            async def handler(websocket):
                # Extension connects and listens for commands
                try:
                    async for message in websocket:
                        pass   # extension can also send us tab info if needed
                except Exception:
                    pass

            async def serve():
                async with websockets.serve(handler, "127.0.0.1", WS_PORT):
                    await asyncio.Future()   # run forever

            asyncio.run(serve())
        except ImportError:
            pass   # websockets not installed — tab closing falls back to window close
        except Exception:
            pass

    # ── run ───────────────────────────────────────────────────────────────────
    def run(self):
        # Start tray in its own thread
        tray_thread = threading.Thread(target=self.tray.run, daemon=True)
        tray_thread.start()
        # Tk mainloop on main thread
        self.root.mainloop()


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # Prompt for key on first run, save to user config
        config_file = Path.home() / ".study_buddy" / "config.json"
        if config_file.exists():
            cfg = json.loads(config_file.read_text())
            os.environ["ANTHROPIC_API_KEY"] = cfg.get("api_key", "")
        else:
            root = tk.Tk()
            root.withdraw()
            key = simpledialog.askstring(
                "API Key",
                "Enter your Anthropic API key (saved locally, never sent anywhere but Anthropic):",
                parent=root
            )
            root.destroy()
            if key:
                config_file.parent.mkdir(parents=True, exist_ok=True)
                config_file.write_text(json.dumps({"api_key": key}))
                os.environ["ANTHROPIC_API_KEY"] = key
            else:
                sys.exit("API key required.")

    app = StudyBuddy()
    app.run()
