// Modes
const MODE_LOCKED_IN = "locked_in";
const MODE_LOCKED_OUT = "locked_out";
const BACKEND_URL = "http://localhost:8000";
const MICRODOSE_USER_ID = "demo-user";
const MICRODOSE_SESSION_ID = "demo-session";
const MICRODOSE_TARGET_COUNT = 20;
const MICRODOSE_POLL_ALARM = "microdose-poll";
const EEG_WS_STORAGE_KEY = "dopamaxxEegWsUrl";
const LOCKED_OUT_CAPTURE_CONFIG_STORAGE_KEY = "lockedOutCaptureConfig";

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
  eegFrames: [],
  eegWsUrl: null,
  ws: null,
  wsConnected: false,
  microdoseReadyCount: 0,
  microdoseRunId: null,
  microdoseRunStatus: null,
  microdoseLastOpenedRunId: null,
  microdoseLastError: null,
};

// ── WebSocket ──────────────────────────────────────────────────────────────

const DEFAULT_EEG_WS_URL = "ws://10.216.66.247:8765/stream/eeg";
const WS_RETRY_MS = 3000;
const EEG_FRAME_TTL_MS = 30000;
const EEG_RECENT_GRACE_MS = 2000;
const EEG_REWARD_SOURCE = "acquisition_inference_v1";
let eegReconnectTimer = null;
let eegConnectSequence = 0;

function connectWebSocket() {
  const sequence = ++eegConnectSequence;
  loadEegWsUrl()
    .then((url) => {
      if (sequence !== eegConnectSequence) return;
      openEegWebSocket(url);
    })
    .catch(() => {
      if (sequence !== eegConnectSequence) return;
      openEegWebSocket(DEFAULT_EEG_WS_URL);
    });
}

function openEegWebSocket(url) {
  if (eegReconnectTimer) {
    clearTimeout(eegReconnectTimer);
    eegReconnectTimer = null;
  }

  try {
    const ws = new WebSocket(url);
    state.ws = ws;
    state.eegWsUrl = url;

    ws.onopen = () => {
      if (state.ws !== ws) return;
      state.wsConnected = true;
      broadcastStatus();
    };

    ws.onmessage = (event) => {
      if (state.ws !== ws) return;
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      handleBackendMessage(msg);
    };

    ws.onclose = () => {
      if (state.ws !== ws) return;
      state.wsConnected = false;
      state.ws = null;
      broadcastStatus();
      scheduleEegReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch {
    scheduleEegReconnect();
  }
}

function scheduleEegReconnect() {
  if (eegReconnectTimer) clearTimeout(eegReconnectTimer);
  eegReconnectTimer = setTimeout(connectWebSocket, WS_RETRY_MS);
}

function reconnectWebSocket() {
  eegConnectSequence += 1;
  if (eegReconnectTimer) {
    clearTimeout(eegReconnectTimer);
    eegReconnectTimer = null;
  }

  const ws = state.ws;
  state.ws = null;
  state.wsConnected = false;
  if (ws) {
    try { ws.close(); } catch {}
  }
  broadcastStatus();
  connectWebSocket();
}

async function loadEegWsUrl() {
  const stored = await chrome.storage.local.get([
    EEG_WS_STORAGE_KEY,
    LOCKED_OUT_CAPTURE_CONFIG_STORAGE_KEY,
  ]);
  const lockedOutConfig = stored[LOCKED_OUT_CAPTURE_CONFIG_STORAGE_KEY] || {};
  return normalizeEegWsUrl(stored[EEG_WS_STORAGE_KEY]) ||
    normalizeEegWsUrl(lockedOutConfig.eegWsUrl) ||
    DEFAULT_EEG_WS_URL;
}

function normalizeEegWsUrl(value) {
  if (typeof value !== "string" || value.trim() === "") return null;

  try {
    const url = new URL(value.trim());
    if (url.protocol === "http:") {
      url.protocol = "ws:";
    } else if (url.protocol === "https:") {
      url.protocol = "wss:";
    } else if (url.protocol !== "ws:" && url.protocol !== "wss:") {
      return null;
    }

    if (!url.pathname || url.pathname === "/") {
      url.pathname = "/stream/eeg";
    }
    return url.toString();
  } catch {
    return null;
  }
}

function handleBackendMessage(msg) {
  if (isAcquisitionEegFrame(msg)) {
    handleAcquisitionEegFrame(msg);
    return;
  }

  // Mode changes come from the signal processing layer which sends
  // { type: "mode_change", mode: "locked_in"|"locked_out" } or
  // { type: "timer_update", seconds_remaining: N }.
  if (state.demoMode) return;

  if (msg.type === "mode_change") {
    setMode(msg.mode);
  } else if (msg.type === "timer_update") {
    state.timerSeconds = msg.seconds_remaining;
    broadcastStatus();
  } else if (msg.type === "scores_update") {
    state.focusScore  = msg.focus_score  ?? state.focusScore;
    state.rewardScore = msg.reward_score ?? state.rewardScore;
    recordEegScoreFrame({
      receivedAtMs: Date.now(),
      rewardScore: boundedNumber(msg.reward_score, -1, 1),
      focusScore: boundedNumber(msg.focus_score, 0, 1),
      rewardLabel: null,
      streamName: "DSI24-EEG",
      sourceMode: "scores_update",
      sampleRateHz: 300,
      channelLabels: null,
    });
    broadcastStatus();
  }
}

function isAcquisitionEegFrame(msg) {
  return Boolean(
    msg &&
    typeof msg === "object" &&
    msg.metadata &&
    typeof msg.metadata === "object" &&
    msg.inference &&
    typeof msg.inference === "object"
  );
}

function handleAcquisitionEegFrame(frame) {
  const inference = frame.inference || {};
  const metadata = frame.metadata || {};
  const rewardScore = boundedNumber(inference.reward_score, -1, 1);
  const focusScore = boundedNumber(inference.focus_score, 0, 1);
  if (rewardScore == null && focusScore == null) return;

  state.rewardScore = rewardScore ?? state.rewardScore;
  state.focusScore = focusScore ?? state.focusScore;

  recordEegScoreFrame({
    receivedAtMs: Date.now(),
    rewardScore,
    focusScore,
    rewardLabel: typeof inference.reward_mood === "string" ? inference.reward_mood : null,
    streamName: typeof metadata.stream_name === "string" ? metadata.stream_name : "DSI24-EEG",
    sourceMode: typeof metadata.source_mode === "string" ? metadata.source_mode : "unknown",
    sampleRateHz: boundedNumber(metadata.sample_rate_hz, 1, 2000) ?? 300,
    channelLabels: Array.isArray(metadata.channel_labels) ? metadata.channel_labels : null,
  });

  broadcastStatus();
}

function recordEegScoreFrame(frame) {
  if (!Array.isArray(state.eegFrames)) state.eegFrames = [];
  if (frame.rewardScore == null && frame.focusScore == null) return;

  state.eegFrames.push({
    received_at_ms: frame.receivedAtMs,
    reward_score: frame.rewardScore,
    focus_score: frame.focusScore,
    reward_label: frame.rewardLabel,
    stream_name: frame.streamName,
    source_mode: frame.sourceMode,
    sample_rate_hz: frame.sampleRateHz,
    channel_labels: frame.channelLabels,
  });
  pruneEegFrames(frame.receivedAtMs);
}

function pruneEegFrames(nowMs) {
  if (!Array.isArray(state.eegFrames)) return;
  const cutoffMs = nowMs - EEG_FRAME_TTL_MS;
  while (state.eegFrames.length > 0 && state.eegFrames[0].received_at_ms < cutoffMs) {
    state.eegFrames.shift();
  }
}

function buildLockedOutEegContext({ epochStartMs, epochEndMs, dwellMs }) {
  const endMs = Number.isFinite(epochEndMs) ? epochEndMs : Date.now();
  const startMs = Number.isFinite(epochStartMs) ? epochStartMs : endMs - Math.max(0, Number(dwellMs) || 0);
  pruneEegFrames(Date.now());

  const frames = Array.isArray(state.eegFrames) ? state.eegFrames : [];
  let selected = frames.filter((frame) => {
    return frame.reward_score != null &&
      frame.received_at_ms >= startMs &&
      frame.received_at_ms <= endMs;
  });

  const latest = frames[frames.length - 1];
  if (
    selected.length === 0 &&
    latest &&
    latest.reward_score != null &&
    Math.abs(endMs - latest.received_at_ms) <= EEG_RECENT_GRACE_MS
  ) {
    selected = [latest];
  }

  if (selected.length === 0) return null;

  const rewardScore = roundScore(mean(selected.map((frame) => frame.reward_score)));
  const focusValues = selected
    .map((frame) => frame.focus_score)
    .filter((value) => value != null);
  const focusScore = focusValues.length > 0 ? roundScore(mean(focusValues)) : null;
  const first = selected[0];
  const last = selected[selected.length - 1];

  return {
    acquisition_schema: "acquisition.websocket.eeg_frame.v1",
    stream_name: first.stream_name || "DSI24-EEG",
    sample_rate_hz: first.sample_rate_hz || 300,
    channel_labels: first.channel_labels || undefined,
    source_mode: first.source_mode || "unknown",
    reward_source: EEG_REWARD_SOURCE,
    reward_model_version: EEG_REWARD_SOURCE,
    epoch_start_ms: Math.round(startMs),
    epoch_end_ms: Math.round(endMs),
    dwell_ms: Math.max(0, Math.round(Number(dwellMs) || 0)),
    frame_count: selected.length,
    coverage_ms: Math.max(0, Math.round(last.received_at_ms - first.received_at_ms)),
    reward_score: rewardScore,
    focus_score: focusScore,
    reward_label: labelReward(rewardScore),
  };
}

function mean(values) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) return null;
  return finite.reduce((sum, value) => sum + value, 0) / finite.length;
}

function boundedNumber(value, low, high) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.max(low, Math.min(high, number));
}

function roundScore(value) {
  if (!Number.isFinite(value)) return null;
  return Math.round(value * 1000000) / 1000000;
}

function labelReward(score) {
  if (!Number.isFinite(score)) return null;
  if (score >= 0.25) return "hit";
  if (score <= -0.25) return "miss";
  return "neutral";
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

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (
    changes[EEG_WS_STORAGE_KEY] ||
    changes[LOCKED_OUT_CAPTURE_CONFIG_STORAGE_KEY]
  ) {
    reconnectWebSocket();
  }
});

// ── Helpers ────────────────────────────────────────────────────────────────

function getStatus() {
  return {
    mode: state.mode,
    demoMode: state.demoMode,
    wsConnected: state.wsConnected,
    eegWsUrl: state.eegWsUrl,
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
globalThis.dopamaxxBuildLockedOutEegContext = buildLockedOutEegContext;

// ── Init ───────────────────────────────────────────────────────────────────

connectWebSocket();
chrome.alarms.create(MICRODOSE_POLL_ALARM, { periodInMinutes: 0.1 });
importScripts("locked_out_capture/background.js");
