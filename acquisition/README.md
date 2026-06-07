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

## Real DSI-24 Mode

```powershell
$env:DOPAMAXX_DSI_BRIDGE_PATH = "C:\eeg-tools\dsi2lsl\dsi2lsl.exe"
python -m acquisition serve --port COM3
```

The bridge path must be absolute so `dsi2lsl.exe` can load its co-located DLLs.
Confirm the headset streams in DSI-Streamer first, then fully close DSI-Streamer
before starting DopaMAXX because the COM port cannot be shared.
