(function () {
  "use strict";

  const MODE_LOCKED_OUT = "locked_out";
  const CAPTURE_MESSAGE = "locked_out_capture_post";
  const CONFIG_STORAGE_KEY = "lockedOutCaptureConfig";
  const BACKEND_URL_STORAGE_KEY = "dopamaxxBackendUrl";
  const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
  const DEFAULT_SUPABASE_FUNCTION_URL =
    "https://kbnbpangliwqthtjpgxm.supabase.co/functions/v1/capture-post";
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
    const payload = buildPayload(capture, config, sender);
    const localResult = await sendLocalReaction(payload, config);
    const supabaseResult = await sendSupabaseObservation(payload, config);

    if (!localResult.ok && !supabaseResult.ok) {
      return {
        ok: false,
        skipped: localResult.skipped && supabaseResult.skipped,
        error: localResult.error || supabaseResult.error || "locked-out capture failed",
        local_error: localResult.error,
        supabase_error: supabaseResult.error,
      };
    }

    console.log(`${LOG_PREFIX} capture-saved`, {
      post_id: payload.platform_post_id,
      local_saved: localResult.ok,
      supabase_saved: supabaseResult.ok,
      local_round_trip_ms: localResult.local_round_trip_ms,
      supabase_round_trip_ms: supabaseResult.supabase_round_trip_ms,
      reward_label: localResult.reward_label || supabaseResult.reward_label,
      reward_score: localResult.reward_score || supabaseResult.reward_score,
      focus_score: localResult.focus_score || supabaseResult.focus_score,
      reward_source: localResult.reward_source || supabaseResult.reward_source,
      embedding_status: supabaseResult.embedding_status,
      embedding_async: supabaseResult.embedding_async,
    });

    return Object.assign(
      { ok: true },
      supabaseResult.ok ? supabaseResult : {},
      localResult.ok ? localResult : {}
    );
  }

  function buildPayload(capture, config, sender) {
    const observedAt = capture.observed_at || new Date().toISOString();
    const observedAtMs = Date.parse(observedAt);
    const dwellMs = Math.max(0, Number(capture.dwell_ms) || 0);
    const epochEndMs = Number.isFinite(observedAtMs) ? observedAtMs : Date.now();
    const epochStartMs = epochEndMs - dwellMs;

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
      eeg_context: buildEegContext({ epochStartMs, epochEndMs, dwellMs }),
      raw_capture: Object.assign({}, capture.raw_capture || {}, {
        tab_id: sender.tab && sender.tab.id,
        frame_id: sender.frameId,
      }),
    };
  }

  function buildEegContext({ epochStartMs, epochEndMs, dwellMs }) {
    if (typeof globalThis.dopamaxxBuildLockedOutEegContext === "function") {
      const liveContext = globalThis.dopamaxxBuildLockedOutEegContext({
        epochStartMs,
        epochEndMs,
        dwellMs,
      });
      if (liveContext && typeof liveContext === "object") return liveContext;
    }

    return {
      acquisition_schema: "acquisition.websocket.eeg_frame.v1",
      stream_name: "DSI24-EEG",
      sample_rate_hz: 300,
      channel_labels: CHANNEL_LABELS,
      source_mode: "random_v0",
      reward_source: "random_v0",
      reward_model_version: "random_v0",
      epoch_start_ms: epochStartMs,
      epoch_end_ms: epochEndMs,
      dwell_ms: dwellMs,
      frame_count: 0,
    };
  }

  async function loadConfig() {
    const stored = await chrome.storage.local.get([CONFIG_STORAGE_KEY, BACKEND_URL_STORAGE_KEY]);
    const config = stored[CONFIG_STORAGE_KEY] || {};
    return {
      supabaseFunctionUrl: String(config.supabaseFunctionUrl || DEFAULT_SUPABASE_FUNCTION_URL).trim(),
      supabaseAnonKey: String(config.supabaseAnonKey || "").trim(),
      backendUrl: normalizeBackendUrl(stored[BACKEND_URL_STORAGE_KEY]) ||
        normalizeBackendUrl(config.backendUrl) ||
        DEFAULT_BACKEND_URL,
      userId: String(config.userId || DEFAULT_USER_ID).trim() || DEFAULT_USER_ID,
    };
  }

  async function sendLocalReaction(payload, config) {
    const rewardScore = numberOrNull(payload.eeg_context && payload.eeg_context.reward_score);
    if (rewardScore == null) {
      return {
        ok: false,
        skipped: true,
        error: "no recent EEG reward score for local reaction",
      };
    }

    const focusScore = numberOrNull(payload.eeg_context && payload.eeg_context.focus_score);
    const sentAtMs = performance.now();
    try {
      const response = await fetch(`${config.backendUrl}/locked-out/reactions`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          user_id: payload.user_id,
          session_id: payload.session_id,
          post: {
            post_id: payload.platform_post_id,
            text: payload.text || "",
            author: payload.author_handle || payload.author_name || null,
            url: payload.canonical_url || null,
            media_urls: Array.isArray(payload.media)
              ? payload.media.map((item) => item.src || item.poster).filter(Boolean)
              : [],
            source: "locked_out_capture_extension",
            metadata: {
              author_name: payload.author_name || null,
              raw_media: Array.isArray(payload.media) ? payload.media : [],
              raw_capture: payload.raw_capture || {},
            },
          },
          reward_score: rewardScore,
          focus_score: focusScore,
          dwell_ms: payload.dwell_ms,
          eeg_features: payload.eeg_context || {},
        }),
      });
      const localRoundTripMs = Math.round(performance.now() - sentAtMs);
      const body = await responseJson(response);
      if (!response.ok) {
        console.warn(`${LOG_PREFIX} local-reaction-error`, {
          post_id: payload.platform_post_id,
          local_round_trip_ms: localRoundTripMs,
          status: response.status,
          error: body && body.error,
        });
        return {
          ok: false,
          error: body && body.detail ? body.detail : `local reaction failed with HTTP ${response.status}`,
          status: response.status,
          local_round_trip_ms: localRoundTripMs,
        };
      }

      return {
        ok: true,
        local_round_trip_ms: localRoundTripMs,
        reward_score: body && body.reaction && body.reaction.reward_score,
        focus_score: body && body.reaction && body.reaction.focus_score,
        reward_label: body && body.reaction && body.reaction.label,
        reward_source: "local_backend",
      };
    } catch (error) {
      return {
        ok: false,
        error: error && error.message ? error.message : String(error),
      };
    }
  }

  async function sendSupabaseObservation(payload, config) {
    if (!config.supabaseFunctionUrl) {
      return {
        ok: false,
        skipped: true,
        error: "supabase capture is not configured",
      };
    }

    const sentAtMs = performance.now();
    let response;
    let body;
    let supabaseRoundTripMs;
    try {
      const headers = {
        "content-type": "application/json",
      };
      if (config.supabaseAnonKey) {
        headers.apikey = config.supabaseAnonKey;
      }

      response = await fetch(config.supabaseFunctionUrl, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      supabaseRoundTripMs = Math.round(performance.now() - sentAtMs);
      body = await responseJson(response);
    } catch (error) {
      return {
        ok: false,
        error: error && error.message ? error.message : String(error),
      };
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

    return Object.assign({ ok: true, supabase_round_trip_ms: supabaseRoundTripMs }, body);
  }

  async function responseJson(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return { error: text };
    }
  }

  function normalizeBackendUrl(value) {
    if (typeof value !== "string" || value.trim() === "") return null;
    try {
      const url = new URL(value.trim());
      if (url.protocol !== "http:" && url.protocol !== "https:") return null;
      url.pathname = url.pathname.replace(/\/+$/, "");
      return url.toString().replace(/\/$/, "");
    } catch {
      return null;
    }
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
