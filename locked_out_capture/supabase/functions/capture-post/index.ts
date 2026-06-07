import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, x-client-info, apikey, content-type",
  "access-control-allow-methods": "POST, OPTIONS",
};

const CHANNEL_LABELS = [
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
];

type CapturePayload = {
  user_id?: string;
  session_id?: string;
  platform?: string;
  platform_post_id?: string;
  canonical_url?: string;
  author_handle?: string;
  author_name?: string;
  text?: string;
  media?: Array<{ type?: string; src?: string; poster?: string; alt?: string }>;
  dwell_ms?: number;
  viewport_score?: number | null;
  center_score?: number | null;
  main_visible_ratio?: number | null;
  observed_at?: string;
  eeg_context?: Record<string, unknown>;
  raw_capture?: Record<string, unknown>;
};

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return jsonResponse({ ok: true }, 200);
  }

  if (request.method !== "POST") {
    return jsonResponse({ ok: false, error: "method not allowed" }, 405);
  }

  try {
    const payload = await request.json() as CapturePayload;
    const normalized = normalizePayload(payload);

    const supabaseUrl = requiredEnv("SUPABASE_URL");
    const serviceRoleKey = supabaseAdminKey();
    const openaiApiKey = Deno.env.get("OPENAI_API_KEY");
    const embeddingModel = Deno.env.get("OPENAI_EMBEDDING_MODEL") || "text-embedding-3-small";
    const supabase = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false },
    });

    const postRow: Record<string, unknown> = {
      platform: normalized.platform,
      platform_post_id: normalized.platform_post_id,
      canonical_url: normalized.canonical_url,
      author_handle: normalized.author_handle,
      author_name: normalized.author_name,
      text: normalized.text,
      media: normalized.media,
      raw_capture: normalized.raw_capture,
      embedding_model: embeddingModel,
    };

    const { data: post, error: postError } = await supabase
      .from("posts")
      .upsert(postRow, { onConflict: "platform,platform_post_id" })
      .select("id,embedding_status")
      .single();

    if (postError) throw postError;

    const embeddingState = scheduleEmbeddingUpdate({
      supabase,
      postId: post.id,
      currentStatus: post.embedding_status,
      apiKey: openaiApiKey,
      model: embeddingModel,
      input: embeddingInput(normalized),
    });

    const eegContext = buildEegContext(normalized);
    const reward = resolveReward(eegContext);

    const { data: existingObservation, error: existingObservationError } = await supabase
      .from("post_observations")
      .select("id,reward_score,reward_label,focus_score,reward_source,reward_model_version,eeg_context")
      .eq("user_id", normalized.user_id)
      .eq("session_id", normalized.session_id)
      .eq("post_id", post.id)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    if (existingObservationError) throw existingObservationError;
    if (existingObservation) {
      return jsonResponse({
        ok: true,
        duplicate: true,
        post_id: post.id,
        observation_id: existingObservation.id,
        reward_score: existingObservation.reward_score,
        reward_label: existingObservation.reward_label,
        focus_score: existingObservation.focus_score ?? focusScoreFromContext(existingObservation.eeg_context),
        reward_source: existingObservation.reward_source,
        reward_model_version: existingObservation.reward_model_version,
        embedding_status: embeddingState.status,
        embedding_async: embeddingState.async,
        embedding_model: embeddingModel,
        embedding_error: embeddingState.error,
      });
    }

    const { data: observation, error: observationError } = await supabase
      .from("post_observations")
      .insert({
        user_id: normalized.user_id,
        session_id: normalized.session_id,
        post_id: post.id,
        mode: "locked_out",
        dwell_ms: normalized.dwell_ms,
        viewport_score: normalized.viewport_score,
        center_score: normalized.center_score,
        main_visible_ratio: normalized.main_visible_ratio,
        reward_source: reward.source,
        reward_model_version: reward.modelVersion,
        reward_score: reward.score,
        reward_label: reward.label,
        focus_score: reward.focusScore,
        eeg_context: eegContext,
        raw_observation: {
          capture: normalized.raw_capture,
          reward: {
            source: reward.source,
            thresholds: { hit_gte: 0.25, miss_lte: -0.25 },
            focus_score: reward.focusScore,
          },
        },
        observed_at: normalized.observed_at,
      })
      .select("id")
      .single();

    if (observationError) throw observationError;

    return jsonResponse({
      ok: true,
      post_id: post.id,
      observation_id: observation.id,
      reward_score: reward.score,
      reward_label: reward.label,
      focus_score: reward.focusScore,
      reward_source: reward.source,
      reward_model_version: reward.modelVersion,
      embedding_status: embeddingState.status,
      embedding_async: embeddingState.async,
      embedding_model: embeddingModel,
      embedding_error: embeddingState.error,
    });
  } catch (error) {
    return jsonResponse({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    }, 400);
  }
});

function normalizePayload(payload: CapturePayload) {
  const platformPostId = requireString(payload.platform_post_id, "platform_post_id");
  const platform = (payload.platform || "x").toLowerCase();
  if (platform !== "x" && platform !== "twitter") {
    throw new Error("platform must be x or twitter");
  }

  const observedAt = payload.observed_at || new Date().toISOString();
  if (Number.isNaN(Date.parse(observedAt))) {
    throw new Error("observed_at must be an ISO timestamp");
  }

  return {
    user_id: requireString(payload.user_id || "demo_user", "user_id"),
    session_id: requireString(payload.session_id, "session_id"),
    platform,
    platform_post_id: platformPostId,
    canonical_url: optionalString(payload.canonical_url),
    author_handle: optionalString(payload.author_handle),
    author_name: optionalString(payload.author_name),
    text: optionalString(payload.text),
    media: Array.isArray(payload.media) ? payload.media : [],
    dwell_ms: Math.max(0, Math.round(Number(payload.dwell_ms) || 0)),
    viewport_score: optionalNumber(payload.viewport_score),
    center_score: optionalNumber(payload.center_score),
    main_visible_ratio: optionalNumber(payload.main_visible_ratio),
    observed_at: observedAt,
    eeg_context: payload.eeg_context && typeof payload.eeg_context === "object" ? payload.eeg_context : {},
    raw_capture: payload.raw_capture && typeof payload.raw_capture === "object" ? payload.raw_capture : {},
  };
}

function scheduleEmbeddingUpdate(options: {
  supabase: ReturnType<typeof createClient>;
  postId: string;
  currentStatus: string | null;
  apiKey: string | undefined;
  model: string;
  input: string;
}) {
  if (options.currentStatus === "complete") {
    return {
      status: "complete",
      async: false,
      error: null,
    };
  }

  if (!options.apiKey) {
    const error = "OPENAI_API_KEY is not configured";
    runInBackground(markEmbeddingFailed({
      supabase: options.supabase,
      postId: options.postId,
      model: options.model,
      error,
    }));

    return {
      status: "failed",
      async: false,
      error,
    };
  }

  runInBackground(updatePostEmbedding(options));

  return {
    status: "pending",
    async: true,
    error: null,
  };
}

function runInBackground(promise: Promise<unknown>) {
  const edgeRuntime = (globalThis as {
    EdgeRuntime?: { waitUntil?: (promise: Promise<unknown>) => void };
  }).EdgeRuntime;

  if (typeof edgeRuntime?.waitUntil === "function") {
    edgeRuntime.waitUntil(promise);
    return;
  }

  promise.catch((error) => {
    console.error("locked-out embedding background task failed", error);
  });
}

async function updatePostEmbedding(options: {
  supabase: ReturnType<typeof createClient>;
  postId: string;
  apiKey: string;
  model: string;
  input: string;
}) {
  try {
    const { error: pendingError } = await options.supabase
      .from("posts")
      .update({
        embedding_status: "pending",
        embedding_model: options.model,
        embedding_error: null,
      })
      .eq("id", options.postId)
      .neq("embedding_status", "complete");

    if (pendingError) throw pendingError;

    const embeddingResult = await createEmbedding({
      apiKey: options.apiKey,
      model: options.model,
      input: options.input,
    });

    if (!embeddingResult.ok) {
      await markEmbeddingFailed({
        supabase: options.supabase,
        postId: options.postId,
        model: options.model,
        error: embeddingResult.error,
      });
      return;
    }

    const { error: updateError } = await options.supabase
      .from("posts")
      .update({
        embedding: embeddingResult.embedding,
        embedding_model: options.model,
        embedding_status: "complete",
        embedding_error: null,
      })
      .eq("id", options.postId)
      .neq("embedding_status", "complete");

    if (updateError) throw updateError;
  } catch (error) {
    console.error("locked-out embedding update failed", error);
  }
}

async function markEmbeddingFailed(options: {
  supabase: ReturnType<typeof createClient>;
  postId: string;
  model: string;
  error: string;
}) {
  const { error: updateError } = await options.supabase
    .from("posts")
    .update({
      embedding_model: options.model,
      embedding_status: "failed",
      embedding_error: options.error,
    })
    .eq("id", options.postId)
    .neq("embedding_status", "complete");

  if (updateError) throw updateError;
}

async function createEmbedding(options: { apiKey: string | undefined; model: string; input: string }) {
  if (!options.apiKey) {
    return {
      ok: false as const,
      error: "OPENAI_API_KEY is not configured",
    };
  }

  try {
    const response = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        "authorization": `Bearer ${options.apiKey}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: options.model,
        input: options.input,
      }),
    });

    const body = await response.json();
    if (!response.ok) {
      return {
        ok: false as const,
        error: body?.error?.message || `OpenAI embeddings failed with HTTP ${response.status}`,
      };
    }

    const embedding = body?.data?.[0]?.embedding;
    if (!Array.isArray(embedding) || embedding.length !== 1536) {
      return {
        ok: false as const,
        error: "OpenAI embedding response did not contain a 1536-dim vector",
      };
    }

    return { ok: true as const, embedding };
  } catch (error) {
    return {
      ok: false as const,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function embeddingInput(payload: ReturnType<typeof normalizePayload>) {
  const mediaAlt = payload.media
    .map((item) => item && typeof item.alt === "string" ? item.alt : "")
    .filter(Boolean)
    .join("\n");

  return [
    payload.author_name ? `Author: ${payload.author_name}` : "",
    payload.author_handle ? `Handle: @${payload.author_handle}` : "",
    payload.text ? `Post: ${payload.text}` : "",
    mediaAlt ? `Media alt text: ${mediaAlt}` : "",
    payload.canonical_url ? `URL: ${payload.canonical_url}` : "",
  ].filter(Boolean).join("\n");
}

function buildEegContext(payload: ReturnType<typeof normalizePayload>) {
  const observedAtMs = Date.parse(payload.observed_at);
  const input = payload.eeg_context as Record<string, unknown>;
  const fallbackEpochStartMs = observedAtMs - payload.dwell_ms;
  const epochStartMs = optionalNumber(input.epoch_start_ms) ?? fallbackEpochStartMs;
  const epochEndMs = optionalNumber(input.epoch_end_ms) ?? observedAtMs;
  const rewardScore = boundedNumber(input.reward_score, -1, 1);
  const focusScore = boundedNumber(input.focus_score, 0, 1);
  const rewardSource = optionalString(input.reward_source) || "random_v0";
  const rewardModelVersion = optionalString(input.reward_model_version) || rewardSource;
  const context: Record<string, unknown> = {
    acquisition_schema: "acquisition.websocket.eeg_frame.v1",
    stream_name: "DSI24-EEG",
    sample_rate_hz: 300,
    channel_labels: CHANNEL_LABELS,
    source_mode: optionalString(input.source_mode) || "random_v0",
    reward_source: rewardSource,
    reward_model_version: rewardModelVersion,
    epoch_start_ms: Math.round(epochStartMs),
    epoch_end_ms: Math.round(epochEndMs),
    dwell_ms: Math.max(0, Math.round(optionalNumber(input.dwell_ms) ?? payload.dwell_ms)),
    frame_count: Math.max(0, Math.round(optionalNumber(input.frame_count) ?? 0)),
  };

  const coverageMs = optionalNumber(input.coverage_ms);
  if (coverageMs !== null) context.coverage_ms = Math.max(0, Math.round(coverageMs));
  if (rewardScore !== null) {
    context.reward_score = roundScore(rewardScore);
    context.reward_label = labelReward(rewardScore);
  }
  if (focusScore !== null) context.focus_score = roundScore(focusScore);

  return context;
}

function resolveReward(eegContext: Record<string, unknown>) {
  const eegRewardScore = boundedNumber(eegContext.reward_score, -1, 1);
  if (eegRewardScore !== null) {
    const score = roundScore(eegRewardScore);
    return {
      score,
      label: labelReward(score),
      source: "acquisition_inference_v1",
      modelVersion: "acquisition_inference_v1",
      focusScore: focusScoreFromContext(eegContext),
    };
  }

  const score = randomRewardScore();
  return {
    score,
    label: labelReward(score),
    source: "random_v0",
    modelVersion: "random_v0",
    focusScore: null,
  };
}

function randomRewardScore() {
  return roundScore(Math.random() * 2 - 1);
}

function labelReward(score: number) {
  if (score >= 0.25) return "hit";
  if (score <= -0.25) return "miss";
  return "neutral";
}

function focusScoreFromContext(eegContext: unknown) {
  if (!eegContext || typeof eegContext !== "object") return null;
  return boundedNumber((eegContext as Record<string, unknown>).focus_score, 0, 1);
}

function requiredEnv(name: string) {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

function supabaseAdminKey() {
  const legacyServiceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacyServiceRoleKey) return legacyServiceRoleKey;

  const secretKeysJson = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (secretKeysJson) {
    const secretKeys = JSON.parse(secretKeysJson) as Record<string, string>;
    const defaultSecretKey = secretKeys.default;
    if (defaultSecretKey) return defaultSecretKey;
  }

  throw new Error("SUPABASE_SECRET_KEYS.default or SUPABASE_SERVICE_ROLE_KEY is required");
}

function requireString(value: unknown, fieldName: string) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${fieldName} is required`);
  }
  return value.trim();
}

function optionalString(value: unknown) {
  return typeof value === "string" ? value.trim() : null;
}

function optionalNumber(value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function boundedNumber(value: unknown, low: number, high: number) {
  const number = optionalNumber(value);
  if (number === null) return null;
  return Math.max(low, Math.min(high, number));
}

function roundScore(value: number) {
  return Math.round(value * 1000000) / 1000000;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders,
      "content-type": "application/json",
    },
  });
}
