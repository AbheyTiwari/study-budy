const WS_URL = 'ws://127.0.0.1:7432';
let ws = null;

const SAFE = ['nptel','gate','pyq','mathoverflow','stackexchange','stackoverflow',
              'wikipedia','arxiv','jupyter','colab','kaggle','leetcode','geeksforgeeks',
              'localhost','127.0.0.1'];

function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen  = () => console.log('[StudyBuddy] connected');
  ws.onclose = () => setTimeout(connect, 15000);
  ws.onerror = () => ws.close();
  ws.onmessage = async ({ data }) => {
    let msg; try { msg = JSON.parse(data); } catch { return; }
    if (msg.action === 'close_tab') await closeTab(msg.hint || '');
  };
}

async function closeTab(hint) {
  const tabs = await chrome.tabs.query({});
  let target = hint
    ? tabs.find(t => t.url?.toLowerCase().includes(hint.toLowerCase()) ||
                     t.title?.toLowerCase().includes(hint.toLowerCase()))
    : null;
  if (!target) {
    const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    target = active;
  }
  if (!target) return;
  const url = (target.url || '').toLowerCase();
  if (!SAFE.some(p => url.includes(p))) {
    chrome.tabs.remove(target.id);
  }
}

connect();
