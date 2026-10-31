/**
 * Study Buddy — Browser Extension Background Service Worker
 * Connects to the Python app's WebSocket server on localhost:7432
 * Receives close-tab commands and closes the active/distraction tab.
 */

const WS_URL = "ws://127.0.0.1:7432";
let ws = null;
let reconnectTimer = null;

function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return;
  }

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("[StudyBuddy] Connected to desktop app");
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onmessage = async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      return;
    }

    if (msg.action === "close_tab") {
      await closeDistractionTab(msg.hint || "");
    }
  };

  ws.onclose = () => {
    console.log("[StudyBuddy] Disconnected — will retry in 30s");
    reconnectTimer = setTimeout(connect, 30000);
  };

  ws.onerror = (err) => {
    ws.close();
  };
}

async function closeDistractionTab(hint) {
  // Get all tabs in all windows
  const tabs = await chrome.tabs.query({});

  // Try to match the hint (URL fragment or title substring)
  let target = null;
  if (hint) {
    const hintLower = hint.toLowerCase();
    target = tabs.find(
      (t) =>
        (t.url && t.url.toLowerCase().includes(hintLower)) ||
        (t.title && t.title.toLowerCase().includes(hintLower))
    );
  }

  // Fallback: close the currently active tab in the focused window
  if (!target) {
    const active = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (active.length > 0) {
      target = active[0];
    }
  }

  if (target) {
    // Don't close if it looks like a study resource
    const safePatterns = [
      "localhost",
      "127.0.0.1",
      "youtube.com/watch",   // might be a lecture — let Python app decide
      "nptel",
      "gate",
      "pyq",
      "mathoverflow",
      "stackexchange",
      "stackoverflow",
      "wikipedia",
      "arxiv",
      "pdf",
      "jupyter",
      "colab",
      "kaggle",
      "leetcode",
      "geeksforgeeks",
    ];

    const url = (target.url || "").toLowerCase();
    const isSafe = safePatterns.some((p) => url.includes(p));

    if (!isSafe) {
      console.log("[StudyBuddy] Closing tab:", target.title, target.url);
      await chrome.tabs.remove(target.id);
    } else {
      console.log("[StudyBuddy] Tab looks like study material, skipping close:", target.url);
    }
  }
}

// Start connecting immediately when service worker starts
connect();

// Reconnect when the extension icon is clicked
chrome.action.onClicked.addListener(() => {
  connect();
});
