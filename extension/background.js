// Modes
const MODE_LOCKED_IN = "locked_in";
const MODE_LOCKED_OUT = "locked_out";

const DISTRACTING_SITES = [
  "twitter.com", "x.com",
  "youtube.com",
  "reddit.com",
  "instagram.com",
  "tiktok.com",
  "facebook.com",
  "netflix.com",
  "twitch.tv",
  "linkedin.com",
];

let state = {
  mode: MODE_LOCKED_OUT,
  workTabId: null,
  demoMode: false,
  timerSeconds: 0,
  ws: null,
  wsConnected: false,
};

// ── WebSocket ──────────────────────────────────────────────────────────────

const WS_URL = "ws://localhost:8000/stream/eeg";
const WS_RETRY_MS = 3000;

function connectWebSocket() {
  try {
    state.ws = new WebSocket(WS_URL);

    state.ws.onopen = () => {
      state.wsConnected = true;
      broadcastStatus();
    };

    state.ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      handleBackendMessage(msg);
    };

    state.ws.onclose = () => {
      state.wsConnected = false;
      state.ws = null;
      broadcastStatus();
      setTimeout(connectWebSocket, WS_RETRY_MS);
    };

    state.ws.onerror = () => {
      state.ws?.close();
    };
  } catch {
    setTimeout(connectWebSocket, WS_RETRY_MS);
  }
}

function handleBackendMessage(msg) {
  // EEG frames from the acquisition service (msg has .samples, .channel_labels, etc.)
  // Just keep the connection alive for now; mode changes come from the signal
  // processing layer which sends { type: "mode_change", mode: "locked_in"|"locked_out" }
  // or { type: "timer_update", seconds_remaining: N }.
  if (state.demoMode) return;

  if (msg.type === "mode_change") {
    setMode(msg.mode);
  } else if (msg.type === "timer_update") {
    state.timerSeconds = msg.seconds_remaining;
    broadcastStatus();
  }
  // EEG frames (no .type) are silently consumed — connection staying alive is enough.
}

// ── Mode management ────────────────────────────────────────────────────────

function setMode(newMode) {
  if (newMode === state.mode) return;
  state.mode = newMode;

  if (newMode === MODE_LOCKED_IN) {
    // Remember which tab is the work tab right now
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) state.workTabId = tabs[0].id;
      broadcastStatus();
    });
  } else {
    broadcastStatus();
  }

  // Tell all content scripts about the mode change
  chrome.tabs.query({}, (tabs) => {
    for (const tab of tabs) {
      chrome.tabs.sendMessage(tab.id, { type: "mode_change", mode: newMode }).catch(() => {});
    }
  });
}

// ── Distraction blocking ───────────────────────────────────────────────────

function isDistracting(url) {
  if (!url) return false;
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return DISTRACTING_SITES.some((site) => host === site || host.endsWith("." + site));
  } catch {
    return false;
  }
}

function redirectToBlocked(tabId) {
  const blockedUrl = chrome.runtime.getURL("blocked.html");
  chrome.tabs.update(tabId, { url: blockedUrl }).catch(() => {});
}

// Block on tab activation (user switches to a distracting tab)
chrome.tabs.onActivated.addListener(({ tabId }) => {
  if (state.mode !== MODE_LOCKED_IN) return;
  chrome.tabs.get(tabId, (tab) => {
    if (chrome.runtime.lastError) return;
    if (isDistracting(tab.url)) {
      // Switch back to work tab if we still have it, else just block
      if (state.workTabId && state.workTabId !== tabId) {
        chrome.tabs.update(state.workTabId, { active: true }).catch(() => {});
      } else {
        redirectToBlocked(tabId);
      }
    }
  });
});

// Block on navigation (user types a distracting URL or a link navigates there)
chrome.webNavigation.onBeforeNavigate.addListener(({ tabId, url, frameId }) => {
  if (frameId !== 0) return; // main frame only
  if (state.mode !== MODE_LOCKED_IN) return;
  if (isDistracting(url)) {
    redirectToBlocked(tabId);
  }
});

// Also catch tab URL updates (covers edge cases like JS-driven navigation)
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (state.mode !== MODE_LOCKED_IN) return;
  if (!changeInfo.url) return;
  if (isDistracting(changeInfo.url)) {
    // Give the tab a moment to actually load before redirecting
    setTimeout(() => redirectToBlocked(tabId), 50);
  }
});

// ── Demo mode toggle (called from popup) ──────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "get_status") {
    sendResponse(getStatus());
    return true;
  }

  if (msg.type === "demo_toggle_mode") {
    state.demoMode = true;
    const newMode = state.mode === MODE_LOCKED_IN ? MODE_LOCKED_OUT : MODE_LOCKED_IN;
    setMode(newMode);
    sendResponse(getStatus());
    return true;
  }

  if (msg.type === "set_demo_mode") {
    state.demoMode = msg.enabled;
    broadcastStatus();
    sendResponse(getStatus());
    return true;
  }
});

// ── Helpers ────────────────────────────────────────────────────────────────

function getStatus() {
  return {
    mode: state.mode,
    demoMode: state.demoMode,
    wsConnected: state.wsConnected,
    timerSeconds: state.timerSeconds,
    workTabId: state.workTabId,
  };
}

function broadcastStatus() {
  chrome.runtime.sendMessage({ type: "status_update", ...getStatus() }).catch(() => {});
}

// ── Init ───────────────────────────────────────────────────────────────────

connectWebSocket();
