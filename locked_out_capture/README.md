# Locked Out Capture

This folder owns the Supabase/vector side of the Locked Out mode capture flow.
Chrome-loaded code lives under `extension/locked_out_capture/` so it works with
the existing MV3 extension without a build step.

## Flow

1. The content script runs only on `x.com` and `twitter.com`.
2. It chooses the centered, mostly visible tweet and waits until it wins for
   `7000ms`.
3. The extension background script verifies the current mode is `locked_out`.
4. The background script summarizes the acquisition WebSocket frames for that
   dwell window.
5. The background script POSTs the capture to the Supabase Edge Function.
6. The Edge Function upserts `posts`, schedules an OpenAI embedding, and inserts
   `post_observations`.

The extension does not send raw EEG samples. `eeg_context` only stores timing,
frame count, `reward_score`, `focus_score`, and the derived `reward_label`.
If the acquisition service is offline, the Edge Function falls back to
`random_v0` reward data so local testing still works.

## Chrome Configuration

After loading the merged `extension/` directory as an unpacked Chrome extension,
configure the Supabase endpoint from the extension service worker console:

```js
chrome.storage.local.set({
  lockedOutCaptureConfig: {
    supabaseFunctionUrl: "https://kbnbpangliwqthtjpgxm.supabase.co/functions/v1/capture-post",
    supabaseAnonKey: "",
    userId: "demo_user",
    eegWsUrl: "ws://10.216.66.247:8765/stream/eeg"
  }
});
```

The anon key can stay empty for the deployed `dopamaxx` function because
`verify_jwt = false`. The extension never stores the OpenAI key, database
password, or Supabase service-role key.
`eegWsUrl` should point at the acquisition service's derived EEG stream, not
the raw sample stream. The derived stream is what includes `reward_score` and
`focus_score`.

## Supabase Setup

Apply the migration in `supabase/migrations/001_locked_out_capture.sql` to the
Supabase project, then deploy the Edge Function in
`supabase/functions/capture-post`.

Required Edge Function secrets:

```sh
supabase secrets set OPENAI_API_KEY=<openai-api-key>
supabase secrets set OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Supabase provides `SUPABASE_URL` and `SUPABASE_SECRET_KEYS` to deployed
functions. The `capture-post` function has `verify_jwt = false` in
`supabase/config.toml` so it can be called with the newer `sb_publishable_...`
key format.

## Compatibility Notes

- The teammate extension's mode messages remain unchanged: `get_status`,
  `mode_change`, and `status_update`.
- Locked Out capture uses its own message type:
  `locked_out_capture_post`.
- The acquisition-compatible EEG context is defined in `eeg_contract.json` and
  mirrors `acquisition/spec.py`.
- Reward labels are derived from `reward_score`:
  `hit >= 0.25`, `miss <= -0.25`, otherwise `neutral`.
