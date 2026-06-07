# Locked Out Capture

This folder owns the Supabase/vector side of the Locked Out mode capture flow.
Chrome-loaded code lives under `extension/locked_out_capture/` so it works with
the existing MV3 extension without a build step.

## Flow

1. The content script runs only on `x.com` and `twitter.com`.
2. It chooses the centered, mostly visible tweet and waits until it wins for
   `1200ms`.
3. The extension background script verifies the current mode is `locked_out`.
4. The background script POSTs the capture to the Supabase Edge Function.
5. The Edge Function upserts `posts`, creates an OpenAI embedding, generates a
   random fake EEG reward label, and inserts `post_observations`.

The real acquisition service is not consumed yet. Observations still store
`eeg_context` using the current acquisition stream contract so random labels can
be replaced later without changing the database shape.

## Chrome Configuration

After loading the merged `extension/` directory as an unpacked Chrome extension,
configure the Supabase endpoint from the extension service worker console:

```js
chrome.storage.local.set({
  lockedOutCaptureConfig: {
    supabaseFunctionUrl: "https://<project-ref>.functions.supabase.co/capture-post",
    supabaseAnonKey: "<supabase-anon-key>",
    userId: "demo_user"
  }
});
```

The extension never stores the OpenAI key or Supabase service-role key.

## Supabase Setup

Apply the migration in `supabase/migrations/001_locked_out_capture.sql` to the
Supabase project, then deploy the Edge Function in
`supabase/functions/capture-post`.

Required Edge Function secrets:

```sh
supabase secrets set OPENAI_API_KEY=<openai-api-key>
supabase secrets set OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Supabase provides `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to deployed
functions.

## Compatibility Notes

- The teammate extension's mode messages remain unchanged: `get_status`,
  `mode_change`, and `status_update`.
- Locked Out capture uses its own message type:
  `locked_out_capture_post`.
- The acquisition-compatible EEG context is defined in `eeg_contract.json` and
  mirrors `acquisition/spec.py`.
- Reward labels are random for now:
  `hit >= 0.25`, `miss <= -0.25`, otherwise `neutral`.
