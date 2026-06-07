(function () {
  "use strict";

  const MODE_LOCKED_OUT = "locked_out";
  const CAPTURE_MESSAGE = "locked_out_capture_post";
  const CONFIG_STORAGE_KEY = "lockedOutCaptureConfig";
  const DEFAULT_USER_ID = "demo_user";
  const LOG_PREFIX = "[DopaMAXX locked-out]";

  const CHANNEL_LABELS = Object.freeze([
    "Fp1",
    "Fp2",
    "F7",
    "F3",
    "Fz",
    "F4",
    "F8",
    "T3",
    "C3",
    "Cz",
    "C4",
    "T4",
    "T5",
    "P3",
    "Pz",
    "P4",
    "T6",
    "O1",
    "O2",
  ]);

  const sessionId = makeSessionId();

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== CAPTURE_MESSAGE) return undefined;

    handleCaptureMessage(msg.capture, sender)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));

    return true;
  });

  async function handleCaptureMessage(capture, sender) {
    const status = getExtensionStatus();
    if (status.mode !== MODE_LOCKED_OUT) {
      return { ok: false, skipped: true, error: "capture is disabled outside locked_out mode" };
    }

    const config = await loadConfig();
    if (!config.supabaseFunctionUrl || !config.supabaseAnonKey) {
      return {
        ok: false,
        skipped: true,
        error: "locked-out capture is not configured; set lockedOutCaptureConfig in chrome.storage.local",
      };
    }

    const payload = buildPayload(capture, config, sender);
    const sentAtMs = performance.now();
    const response = await fetch(config.supabaseFunctionUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "apikey": config.supabaseAnonKey,
      },
      body: JSON.stringify(payload),
    });
    const supabaseRoundTripMs = Math.round(performance.now() - sentAtMs);

    let body = null;
    try {
      body = await response.json();
    } catch {
      body = { error: await response.text() };
    }

    if (!response.ok) {
      console.log(`${LOG_PREFIX} supabase-error`, {
        post_id: payload.platform_post_id,
        supabase_round_trip_ms: supabaseRoundTripMs,
        status: response.status,
        error: body && body.error,
      });
      return {
        ok: false,
        error: body && body.error ? body.error : `capture failed with HTTP ${response.status}`,
        status: response.status,
        supabase_round_trip_ms: supabaseRoundTripMs,
      };
    }

    console.log(`${LOG_PREFIX} supabase-saved`, {
      post_id: payload.platform_post_id,
      supabase_round_trip_ms: supabaseRoundTripMs,
      reward_label: body && body.reward_label,
      embedding_status: body && body.embedding_status,
      embedding_async: body && body.embedding_async,
    });

    return Object.assign({ ok: true, supabase_round_trip_ms: supabaseRoundTripMs }, body);
  }

  function buildPayload(capture, config, sender) {
    const observedAt = capture.observed_at || new Date().toISOString();
    const observedAtMs = Date.parse(observedAt);
    const dwellMs = Math.max(0, Number(capture.dwell_ms) || 0);
    const epochEndMs = Number.isFinite(observedAtMs) ? observedAtMs : Date.now();

    return {
      user_id: config.userId || DEFAULT_USER_ID,
      session_id: sessionId,
      platform: capture.post && capture.post.platform ? capture.post.platform : "x",
      platform_post_id: capture.post && capture.post.platform_post_id,
      canonical_url: capture.post && capture.post.canonical_url,
      author_handle: capture.post && capture.post.author_handle,
      author_name: capture.post && capture.post.author_name,
      text: capture.post && capture.post.text,
      media: capture.post && capture.post.media ? capture.post.media : [],
      dwell_ms: dwellMs,
      viewport_score: numberOrNull(capture.viewport_score),
      center_score: numberOrNull(capture.center_score),
      main_visible_ratio: numberOrNull(capture.main_visible_ratio),
      observed_at: observedAt,
      eeg_context: {
        acquisition_schema: "acquisition.websocket.eeg_frame.v1",
        stream_name: "DSI24-EEG",
        sample_rate_hz: 300,
        channel_labels: CHANNEL_LABELS,
        source_mode: "random_v0",
        epoch_start_ms: epochEndMs - dwellMs,
        epoch_end_ms: epochEndMs,
      },
      raw_capture: Object.assign({}, capture.raw_capture || {}, {
        tab_id: sender.tab && sender.tab.id,
        frame_id: sender.frameId,
      }),
    };
  }

  async function loadConfig() {
    const stored = await chrome.storage.local.get(CONFIG_STORAGE_KEY);
    const config = stored[CONFIG_STORAGE_KEY] || {};
    return {
      supabaseFunctionUrl: String(config.supabaseFunctionUrl || "").trim(),
      supabaseAnonKey: String(config.supabaseAnonKey || "").trim(),
      userId: String(config.userId || DEFAULT_USER_ID).trim() || DEFAULT_USER_ID,
    };
  }

  function getExtensionStatus() {
    if (typeof globalThis.dopamaxxGetStatus === "function") {
      return globalThis.dopamaxxGetStatus();
    }
    return { mode: MODE_LOCKED_OUT };
  }

  function numberOrNull(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function makeSessionId() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
    return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
})();
