// Modes
const MODE_LOCKED_IN = "locked_in";
const MODE_LOCKED_OUT = "locked_out";
const BACKEND_URL = "http://localhost:8000";
const MICRODOSE_USER_ID = "demo-user";
const MICRODOSE_SESSION_ID = "demo-session";
const MICRODOSE_TARGET_COUNT = 20;
const MICRODOSE_POLL_ALARM = "microdose-poll";

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
  focusScore: null,
  rewardScore: null,
  ws: null,
  wsConnected: false,
  microdoseReadyCount: 0,
  microdoseRunId: null,
  microdoseRunStatus: null,
  microdoseLastOpenedRunId: null,
  microdoseLastError: null,
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
  } else if (msg.type === "scores_update") {
    state.focusScore  = msg.focus_score  ?? state.focusScore;
    state.rewardScore = msg.reward_score ?? state.rewardScore;
    broadcastStatus();
  }
  // EEG frames (no .type) are silently consumed — connection staying alive is enough.
}

// ── Microdose feed ────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(MICRODOSE_POLL_ALARM, { periodInMinutes: 0.1 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== MICRODOSE_POLL_ALARM) return;
  pollMicrodoseFeed({ openWhenReady: true }).catch((error) => {
    state.microdoseLastError = String(error);
    broadcastStatus();
  });
});

async function startMicrodoseRun() {
  state.microdoseLastError = null;
  const response = await fetch(`${BACKEND_URL}/agent/autoscroll/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: MICRODOSE_USER_ID,
      session_id: MICRODOSE_SESSION_ID,
      target_count: MICRODOSE_TARGET_COUNT,
      timeout_s: 45,
      query_context: { trigger: "chrome_extension_demo" },
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`autoscroll start failed: ${response.status} ${detail}`);
  }

  const payload = await response.json();
  state.microdoseRunId = payload.run?.run_id ?? null;
  state.microdoseRunStatus = payload.run?.status ?? "running";
  state.microdoseReadyCount = 0;
  broadcastStatus();
  pollMicrodoseFeed({ openWhenReady: false }).catch(() => {});
  return getStatus();
}

async function pollMicrodoseFeed({ openWhenReady }) {
  const items = await fetchMicrodoseItems();
  state.microdoseReadyCount = items.length;
  state.microdoseLastError = null;

  const runId = items[0]?.run_id ?? state.microdoseRunId;
  if (
    openWhenReady &&
    items.length >= MICRODOSE_TARGET_COUNT &&
    runId &&
    state.microdoseLastOpenedRunId !== runId
  ) {
    state.microdoseLastOpenedRunId = runId;
    await openMicrodoseFeed();
  }

  broadcastStatus();
  return { status: getStatus(), items };
}

async function fetchMicrodoseItems() {
  const url = new URL(`${BACKEND_URL}/feed/microdose`);
  url.searchParams.set("user_id", MICRODOSE_USER_ID);
  url.searchParams.set("session_id", MICRODOSE_SESSION_ID);
  url.searchParams.set("limit", String(MICRODOSE_TARGET_COUNT));

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`microdose feed failed: ${response.status}`);
  }
  const payload = await response.json();
  return payload.items ?? [];
}

async function updateMicrodoseItem(queueId, status) {
  const response = await fetch(`${BACKEND_URL}/feed/microdose/${queueId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    throw new Error(`microdose item update failed: ${response.status}`);
  }
  return response.json();
}

async function openMicrodoseFeed() {
  await chrome.windows.create({
    url: chrome.runtime.getURL("feed.html"),
    type: "popup",
    width: 520,
    height: 760,
    focused: true,
  });
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

  if (msg.type === "start_microdose") {
    startMicrodoseRun()
      .then((status) => sendResponse({ ok: true, status }))
      .catch((error) => {
        state.microdoseLastError = String(error);
        broadcastStatus();
        sendResponse({ ok: false, error: String(error), status: getStatus() });
      });
    return true;
  }

  if (msg.type === "poll_microdose_feed") {
    pollMicrodoseFeed({ openWhenReady: false })
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => {
        state.microdoseLastError = String(error);
        broadcastStatus();
        sendResponse({ ok: false, error: String(error), status: getStatus(), items: [] });
      });
    return true;
  }

  if (msg.type === "open_microdose_feed") {
    openMicrodoseFeed()
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (msg.type === "get_microdose_feed") {
    fetchMicrodoseItems()
      .then((items) => sendResponse({ ok: true, items, status: getStatus() }))
      .catch((error) => sendResponse({ ok: false, error: String(error), items: [] }));
    return true;
  }

  if (msg.type === "update_microdose_item") {
    updateMicrodoseItem(msg.queueId, msg.status)
      .then((item) => sendResponse({ ok: true, item }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
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
    focusScore: state.focusScore,
    rewardScore: state.rewardScore,
    workTabId: state.workTabId,
    microdose: {
      backendUrl: BACKEND_URL,
      userId: MICRODOSE_USER_ID,
      sessionId: MICRODOSE_SESSION_ID,
      targetCount: MICRODOSE_TARGET_COUNT,
      readyCount: state.microdoseReadyCount,
      runId: state.microdoseRunId,
      runStatus: state.microdoseRunStatus,
      lastError: state.microdoseLastError,
    },
  };
}

function broadcastStatus() {
  chrome.runtime.sendMessage({ type: "status_update", ...getStatus() }).catch(() => {});
}

globalThis.dopamaxxGetStatus = getStatus;

// ── Init ───────────────────────────────────────────────────────────────────

connectWebSocket();
chrome.alarms.create(MICRODOSE_POLL_ALARM, { periodInMinutes: 0.1 });
importScripts("locked_out_capture/background.js");
