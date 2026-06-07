# DSI-24 Network Streaming

Run this on the DSI capture laptop to make the live EEG stream available to other laptops on the same network:

```powershell
python -m acquisition serve --port COM9 --bridge-path "C:\Users\hocke\OneDrive\Documents\Egra\RLHB\vendor\dsi\windows\dsi2lsl.exe" --host 0.0.0.0 --http-port 8765
```

Current capture laptop IP observed on Wi-Fi: `10.216.66.247`.

Other laptops should use:

| Link | Provides |
|---|---|
| `http://10.216.66.247:8765/` | Live dashboard: EEG strip, topology map, inference, connection health. |
| `http://10.216.66.247:8765/health` | JSON service health and bridge/reader status. |
| `http://10.216.66.247:8765/metadata` | JSON stream metadata: channel labels, sample rate, source mode. |
| `http://10.216.66.247:8765/stream/raw-info` | Binary raw stream protocol metadata. |
| `ws://10.216.66.247:8765/stream/raw` | Fast binary EEG stream for another DopaMAXX machine. |
| `ws://10.216.66.247:8765/stream/raw-json` | Debug-friendly JSON EEG stream, lower throughput than binary. |

Use `/stream/raw` for production consumers. If another laptop cannot connect, check that both machines are on the same network and that Windows Firewall allows inbound Python traffic on port `8765`.
