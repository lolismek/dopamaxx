# DopaMAXX Acquisition

Standalone DSI-24 acquisition and live EEG streaming service for DopaMAXX.

## Install

```powershell
cd C:\Users\hocke\OneDrive\Documents\GitHub\dopamaxx
python -m pip install -e .\acquisition[dev]
```

## Simulator Mode

```powershell
python -m acquisition serve --simulate
```

Open `http://127.0.0.1:8000`.

## Locked In Autoscroll API

The same FastAPI server exposes the demo autoscroll endpoints used by the
Chrome extension:

```powershell
$env:DOPAMAXX_SUPABASE_URL = "https://<project>.supabase.co"
$env:DOPAMAXX_SUPABASE_SERVICE_ROLE_KEY = "<service-role-key>"
$env:DOPAMAXX_TWITTER_MCP_URL = "http://127.0.0.1:9000/mcp"
$env:DOPAMAXX_TWITTER_MCP_FETCH_TOOL = "twitter.search_candidates"
```

If Supabase is not configured, the server uses an in-memory store for local
testing. The MVP stores derived reaction features, labels, embeddings, queue
items, and agent-run state; it does not store raw EEG samples.

Useful routes:

```text
POST /locked-out/reactions
POST /agent/autoscroll/start
POST /agent/autoscroll/cancel
GET  /agent/autoscroll/runs/{run_id}
GET  /feed/microdose?user_id=demo-user&session_id=demo-session
PATCH /feed/microdose/{queue_id}
```

## Real DSI-24 Mode

```powershell
$env:DOPAMAXX_DSI_BRIDGE_PATH = "C:\eeg-tools\dsi2lsl\dsi2lsl.exe"
python -m acquisition serve --port COM3
```

The bridge path must be absolute so `dsi2lsl.exe` can load its co-located DLLs.
Confirm the headset streams in DSI-Streamer first, then fully close DSI-Streamer
before starting DopaMAXX because the COM port cannot be shared.

## Remote Low-Latency Streaming

Run the capture machine on all interfaces:

```powershell
python -m acquisition serve --port COM9 --bridge-path C:\path\to\dsi2lsl.exe --host 0.0.0.0 --http-port 8765
```

Another computer can subscribe to:

- `ws://<capture-ip>:8765/stream/raw` for binary float chunks.
- `ws://<capture-ip>:8765/stream/raw-json` for easier debugging at lower throughput.
- `http://<capture-ip>:8765/stream/raw-info` for protocol metadata.

Binary `/stream/raw` sends one JSON hello message, then binary frames:

```text
uint32 little-endian header_json_length
header_json utf-8
timestamps float64[n_samples]
samples float32[n_samples, n_channels] row-major
```

Query parameters:

- `max_samples=256` caps samples per frame.
- `poll_ms=2` controls idle polling latency.
- `replay=1` starts from the current ring buffer instead of only new samples.

The stream includes monotonically increasing `first_sequence` / `next_sequence`
numbers and a `dropped` flag so remote consumers can detect backpressure.
