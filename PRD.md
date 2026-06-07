# DopaMAXX — Product Requirements Document

**Tagline:** *Work harder, play harder.*

**Status:** Draft v0.1 (PRD only — no implementation)
**Author:** zane, casper, ansh & alex (columbia x waterloo)
**Date:** 2026-06-07
**Single hardware modality:** Wearable Sensing **DSI-24** — wired, 19-channel dry-electrode EEG cap.

---

## 1. Summary

DopaMAXX is an EEG-driven focus companion built around a Pomodoro rhythm. A wired DSI-24 EEG cap streams the user's brain signals in real time, and the app uses those signals to decide:

- **Whether the user is focused or drifting** (drives the work/break rhythm), and
- **Whether a given social-media post excites the user's reward response** (drives content selection).

The product has two modes:

- **Locked In (Work):** The user is in a focused work window. The app monitors EEG for disengagement. If the user starts slacking, the app *microdoses* short bursts of highly-personalized social content (posts predicted to spike the user's dopamine response), surfaced by an agent that scrolls Twitter/X on the user's behalf and retrieves posts similar to ones that previously produced a positive EEG response. The microdose ends as soon as EEG indicates the user has re-engaged.
- **Locked Out (Play):** The user freely scrolls Twitter/X. For every post they dwell on, DopaMAXX reads the EEG response and labels the post as a *hit* (rewarding) or *miss*. These labels continuously train the user's personal preference profile, which feeds back into the Locked In microdosing engine.

The two modes alternate on a **Pomodoro 25/5 cadence** (25 min work / 5 min break), but with a **±2 minute adaptive leeway** around each transition so the timer never rips the user out of a flow state or forces them to keep working once their brain has already checked out.

Because this must be **live-demoed**, a first-class **Demo Mode** is a top priority: it lets an operator drive every state transition (Locked In ↔ Locked Out, trigger/stop a microdose, mark a post as a hit/miss) from manual inputs, and renders a live, screen-shareable dashboard showing the streaming EEG, the current mode/timer, and the posts the model thinks the user will like.

> **Scope note:** This project uses **EEG only**. No eye-tracking, ECG, EMG, or any other modality. The DSI-24 is the sole sensor.

---

## 2. Goals & Non-Goals

### 2.1 Goals

1. Acquire DSI-24 EEG reliably and surface it live (raw scope + derived focus/reward metrics).
2. Detect, in near-real-time, two EEG-derived signals:
   - **Focus / engagement state** (am I working or drifting?).
   - **Reward / "dopamine" response** to a specific stimulus (did I like this post?).
3. Maintain a **per-user preference profile** built from per-post EEG reactions.
4. **Locked Out mode:** label each scrolled post as hit/miss and update the profile.
5. **Locked In mode:** detect slacking, run an agent that retrieves posts similar to known "good" posts, and microdose them until EEG shows re-engagement.
6. **Adaptive Pomodoro timer:** 25/5 with ±2 min flow-aware leeway on transitions.
7. **Demo Mode:** operator-driven transitions + a live, presentable dashboard for a screen-shared demo.

### 2.2 Non-Goals (for this PRD / MVP)

- No clinical or diagnostic claims. "Dopamine" is used colloquially for an EEG-derived reward/engagement proxy, not a literal neurotransmitter measurement.
- No other biosignal modalities.
- No multi-user / cloud account system beyond what a single demo user needs.
- No native mobile app; desktop (Windows) is the target because the DSI-24 bridge is Windows-only.
- No attempt to ship a scientifically validated focus classifier — the MVP uses well-understood band-power heuristics, with a path to a learned model later.

---

## 3. Background & Key Constraints

### 3.1 Why these constraints exist

- **DSI-24 is wired and Windows-only at the driver level.** The vendor LSL bridge (`dsi2lsl.exe`) is a Windows binary, so the acquisition host must be Windows. (Acquisition details in §8.)
- **EEG is the only ground truth we have for "liking."** There is no click/like button instrumentation in scope — the reward label comes from the EEG response time-locked to a post being on screen.
- **Twitter/X access** is required both for the user's own scrolling (Locked Out) and for the agent's retrieval scrolling (Locked In). The exact integration (official API vs. a controlled browser/automation surface) is an open question (§12) but the PRD assumes we can (a) render posts to the user and (b) programmatically fetch candidate posts.

### 3.2 The "Tribe v2 + similarity" preference model (conceptual)

The user references a model "like **Tribe v2**" with "some notion of similarity to the user's specific EEG/preferences." In this PRD that is captured as a **two-part design**:

1. **Post embedding model** (`Tribe v2`, treated as a pluggable component): maps a post (text + image/video features + author/topic metadata) into a dense embedding vector. This is content-side and user-agnostic.
2. **User preference vector(s):** derived from the EEG-labeled history. The user's taste is represented as the embeddings of posts that produced a strong positive reward response (the *hit set*), optionally summarized into one or more centroid "interest clusters."

**Scoring a candidate post = similarity(post embedding, user preference) → predicted reward.** This is effectively **retrieval-augmented**: the *hit set* is the retrieval corpus; the agent's freshly scrolled candidates are scored by nearest-neighbor similarity to that corpus (and penalized by similarity to the *miss set*). See §7.3 for the algorithm.

> Tribe v2 is treated as a black-box embedding provider in this PRD. If it instead exposes a direct relevance/preference score, the same architecture holds — substitute its score for the cosine-similarity step.

---

## 4. Personas & Core Use Cases

- **The Maker (primary user):** A knowledge worker who wants to focus in bursts but is addicted to the dopamine of scrolling. DopaMAXX both protects their focus *and* rewards them with curated content — turning "doomscrolling" into a structured, earned break, and using micro-rewards to pull them back when they drift.
- **The Demo Operator (Egra presenter):** Runs DopaMAXX in front of a live audience. Needs deterministic, manual control over every state and a visually compelling live readout.

### Core use cases

1. *Earned break:* User finishes a 25-min Locked In block; DopaMAXX transitions to Locked Out and serves a feed it expects they'll love.
2. *Drift rescue:* User is Locked In but their EEG focus metric drops. DopaMAXX microdoses 1–3 curated posts; the user gets a hit, re-engages, and the microdose closes.
3. *Taste learning:* During Locked Out, every dwelled-on post is EEG-labeled, sharpening the preference profile used by #2.
4. *Flow protection:* The 25-min timer elapses but EEG shows deep focus; DopaMAXX extends the block by up to 2 min rather than interrupting.
5. *Live demo:* Operator manually flips modes, fires a microdose, and forces a hit/miss label while the audience watches the EEG and post feed update live.

---

## 5. Product Modes & State Machine

### 5.1 Modes

| Mode | Aka | User activity | EEG used for |
|---|---|---|---|
| **Locked In** | Work | Focused work in a constrained window | Detect drift → trigger microdose; detect re-engagement → end microdose |
| **Locked Out** | Play | Free Twitter/X scrolling | Label each post hit/miss → update preference profile |
| **Microdose** | (sub-state of Locked In) | Viewing 1–N curated posts | Detect satisfaction/re-engagement to exit |
| **Demo** | — | Operator-controlled | Manual override of all transitions (see §9) |

### 5.2 State machine

```
                ┌────────────────────── adaptive timer / EEG ──────────────────────┐
                ▼                                                                   │
        ┌───────────────┐   25 min (±2 leeway) elapsed OR sustained drift   ┌───────────────┐
        │   LOCKED IN   │ ────────────────────────────────────────────────► │  LOCKED OUT   │
        │   (Work)      │                                                    │  (Play)       │
        └───────┬───────┘ ◄──────────────────────────────────────────────── └───────────────┘
                │           5 min (±2 leeway) elapsed OR sustained re-engagement
                │
                │ EEG focus drops below threshold for T seconds
                ▼
        ┌───────────────┐
        │  MICRODOSE    │  show curated posts; poll EEG reward
        │ (within Work) │  exit when reward spike + focus recovers, or cap hit
        └───────┬───────┘
                │ re-engaged OR microdose cap reached
                ▼
            back to LOCKED IN
```

**Microdose caps (defaults, tunable):** max 3 posts per microdose, max 1 microdose per 90 s, hard ceiling of N microdoses per Locked In block (prevents the rescue mechanism from itself becoming a distraction loop).

---

## 6. The Adaptive Pomodoro Timer

### 6.1 Behavior

- Nominal cycle: **25 min Locked In → 5 min Locked Out**, repeating.
- Each transition has a **±2 min leeway window** governed by EEG state, not just the clock:

| Situation at the boundary | EEG reading | Action |
|---|---|---|
| Locked In timer hits 25:00 | Still deeply focused (high engagement) | **Extend** Locked In by up to +2 min, re-check; transition the moment focus dips or +2 cap is hit. |
| Locked In approaching 25:00 (within −2 min) | Already drifting / repeatedly slacking | **Early break:** transition to Locked Out up to 2 min early instead of fighting the drift. |
| Locked Out timer hits 5:00 | Still highly rewarded / "in the scroll" | Allow up to +2 min, then firmly transition back to Locked In. |
| Locked Out approaching 5:00 | Reward response flat / bored | Offer early return to Locked In (up to 2 min early). |

### 6.2 Why

A strict timer either interrupts a flow state (costly to regain) or forces continued "work" after the brain has disengaged (low-value, frustrating). The leeway turns the timer into a *negotiation* with the user's measured cognitive state. The leeway is **bounded** (±2 min) so the Pomodoro structure still holds and the demo stays predictable.

### 6.3 Parameters (config-driven)

```
work_minutes            = 25
break_minutes           = 5
leeway_minutes          = 2          # applies to both boundaries
drift_dwell_seconds     = 20         # sustained drift before early-break is offered
flow_extension_check_s  = 30         # re-poll cadence during a leeway extension
```

---

## 7. EEG Signal Processing & Models

> All numbers below are **MVP defaults / heuristics** to be calibrated per user during onboarding (§7.4). They are intentionally simple and explainable for v1; §7.5 describes the upgrade path.

### 7.1 Signal pipeline (shared)

1. **Acquire** 19-ch @ 300 Hz from the `DSI24-EEG` LSL stream (§8).
2. **Preprocess** per analysis window:
   - Band-pass 1–40 Hz, notch at mains (50/60 Hz).
   - Re-reference (common average reference across the 19 scalp channels).
   - Simple artifact gating: drop windows where any channel exceeds an amplitude threshold (blink/motion) or where electrode variance collapses to ~0 (disconnected lead). The live-view code's "near-zero variance ⇒ treat as flat/unplugged" heuristic informs this.
3. **Feature extraction** per window: per-channel band power in θ (4–8 Hz), α (8–13 Hz), β (13–30 Hz), and frontal-midline θ; plus engagement-relevant ratios.

### 7.2 Focus / engagement metric (drives the timer & drift detection)

- **Engagement index** (classic, explainable): `β / (α + θ)` over frontal-central channels (e.g., Fz, Cz, F3, F4). Higher ⇒ more engaged.
- **Frontal-midline theta** (Fz) elevation is associated with sustained concentration; used as a secondary confirmer.
- **Frontal alpha** rise is treated as a drift/disengagement signal.
- Output: a smoothed `focus_score ∈ [0,1]` (e.g., 4 s window, 1 s hop, EWMA-smoothed).
- **Drift trigger (Locked In):** `focus_score` below `drift_threshold` for `drift_dwell_seconds` ⇒ start a microdose.
- **Re-engagement (exit microdose):** `focus_score` back above `reengage_threshold` (with hysteresis to avoid flapping).

### 7.3 Reward / "dopamine" response metric (drives post labeling)

Each post that is **on screen and dwelled on** defines a stimulus epoch. For that epoch we compute a **reward score** from EEG:

- **Frontal alpha asymmetry (FAA):** relative left-vs-right frontal alpha (e.g., F3 vs F4 / Fp1 vs Fp2). Greater left-frontal activity (less left alpha) is a well-known correlate of approach motivation / positive affect. This is the primary "did they like it" proxy.
- **Beta/engagement bump** time-locked to the post appearing (orienting + interest).
- **Theta** modulation as a secondary feature.
- Output: `reward_score ∈ [-1, 1]`; thresholded into **hit** (≥ `hit_threshold`), **miss** (≤ `miss_threshold`), or **neutral** (in between, discarded for training).

**Dwell gating:** A post must be on screen ≥ `min_dwell_ms` (e.g., 1200 ms) before its epoch is scored, so flicked-past posts don't generate noise.

### 7.4 Preference profile & content scoring (the "Tribe v2 + similarity / RAG" engine)

**Data structures:**

- **Hit set `H`:** embeddings of posts labeled *hit*, with reward weights.
- **Miss set `M`:** embeddings of posts labeled *miss*.
- **Interest centroids:** optional k-means over `H` to capture multiple distinct tastes (e.g., "AI research" vs "climbing memes").

**Embedding:** every post → vector via the post embedding model (Tribe v2 black box; §3.2).

**Scoring a candidate post `c` (used by the Locked In agent):**

```
sim_hit(c)  = max/weighted-mean cosine similarity of c to H (or to nearest interest centroid)
sim_miss(c) = weighted-mean cosine similarity of c to M
predicted_reward(c) = sim_hit(c) − λ · sim_miss(c)         # λ tunes "avoid the misses"
```

Candidates are ranked by `predicted_reward`; the top ones are microdosed. This is the RAG framing: **`H` is the retrieval corpus, the agent's scroll yields candidates, similarity retrieves the best-matching "known good" neighborhood.**

**Online update (Locked Out):** each new hit/miss appends to `H`/`M` and (optionally) updates centroids incrementally, so taste tracking is continuous rather than batch.

### 7.5 Upgrade path (post-MVP, non-blocking)

- Replace hand-tuned thresholds with a **calibrated per-user classifier** trained during onboarding (labeled "liked vs disliked" content shown while recording EEG).
- Learn `λ` and thresholds from the user's own hit/miss separation.
- Replace cosine similarity with a small learned **preference head** on top of Tribe v2 embeddings, trained on the EEG reward labels (a true reward model).

### 7.6 Onboarding / calibration (lightweight, ~3–5 min)

- Baseline rest recording (eyes-open/eyes-closed) to set per-user band-power baselines.
- A short labeled scroll (user shown a spread of content) to seed `H`/`M` and set `hit/miss/drift/reengage` thresholds relative to that user's distribution.

---

## 8. DSI-24 EEG Acquisition (grounded in `rlhb-mvp`)

> This section is the authoritative reference for **how DopaMAXX gets EEG data**. All patterns below are taken from the Egra `rlhb-mvp` codebase (`C:\Users\hocke\OneDrive\Documents\Egra\rlhb-mvp`) and are reused, not reinvented. DopaMAXX does **not** need the full `rlhb` modality framework — it needs exactly the DSI-24 acquisition slice documented here.

### 8.1 What the DSI-24 looks like on the wire

From `src/rlhb/modalities/dsi24.py`:

- **LSL stream name:** `DSI24-EEG`
- **Stream type:** `EEG`
- **Channels:** 19, **fixed** 300 Hz
- **Channel labels (canonical anterior→posterior 10-20 order):**
  `Fp1, Fp2, F7, F3, Fz, F4, F8, T3, C3, Cz, C4, T4, T5, P3, Pz, P4, T6, O1, O2`
- **Real driver is Windows-only** — it shells out to the vendor binary `dsi2lsl.exe`, which reads the headset over a serial COM port and republishes onto LSL.

### 8.2 Bringing the stream up (the producer side)

The vendor bridge is launched as an external process. The command template (from the `dsi24` modality spec) is:

```
dsi2lsl.exe --port=<COM_PORT> --lsl-stream-name=DSI24-EEG
```

Operational requirements (from `rlhb-mvp` setup + debugging notes — **carry these into DopaMAXX**):

- **`RLHB_DSI_BRIDGE_PATH` must be an absolute path** to `dsi2lsl.exe`. The exe loads co-located DLLs (`libDSI-Windows-x86_32.dll`, `liblsl32.dll`, `Qt*.dll`, `mingwm10.dll`); the launcher must set `cwd` to the exe's own directory or the DLL loads fail silently. DopaMAXX should resolve the bridge path exactly like `rlhb.config.dsi_bridge_path()` (env var → config file → bare name fallback) and launch with `cwd = Path(exe).resolve().parent`.
- **COM port is host-specific** and must be passed explicitly. (`rlhb`'s `COM4` default is stale; the working wired/wireless ports have varied — pick the correct port per machine.)
- **Cold start is slow (~12 s)** and the first `Master.DataAcquisitionMode` command typically retries a few times even on a healthy unit. Allow a **60 s launch timeout** and a **~3 s settle window** before trusting the stream (mirrors the DSI-24 `HealthCheck(settle_s=3.0, launch_timeout_s=60.0)`).
- **Failure signature to surface in the UI:** `"Connected to COM…"` followed by repeated `Master.DataAcquisitionMode` retries and `"Command failed too many times"` ⇒ **headset is off / asleep / dead battery / paired elsewhere.** The only fix is a physical power-cycle. DopaMAXX's connection panel should detect this pattern and tell the operator to power-cycle the cap.

### 8.3 Consuming the stream (the DopaMAXX side)

DopaMAXX is an **LSL consumer**. The minimal, proven pattern (adapted from `tools/live_view_dsi24.py` and `acquisition/lsl_utils.py`):

```python
import numpy as np
from pylsl import StreamInlet, resolve_byprop

# 1. Resolve the stream by name (poll until it appears or timeout).
streams = resolve_byprop("name", "DSI24-EEG", timeout=20.0)
if not streams:
    raise RuntimeError("DSI24-EEG not found — is the bridge running?")

# 2. Open an inlet. max_buflen MUST be an int (float crashes the ctypes layer).
inlet = StreamInlet(streams[0], max_buflen=60)

info   = inlet.info()
srate  = float(info.nominal_srate()) or 300.0   # 300 Hz nominal
n_ch   = info.channel_count()                    # 19

# 3. Read channel labels from the LSL desc XML (10-20 montage order).
ch = info.desc().child("channels").child("channel")
labels = []
for _ in range(n_ch):
    labels.append(ch.child_value("label") or f"ch{len(labels)+1}")
    ch = ch.next_sibling()

# 4. Pull chunks in a reader loop (single-producer thread feeds a ring buffer).
while running:
    chunk, timestamps = inlet.pull_chunk(timeout=0.25, max_samples=512)
    if chunk:
        samples = np.asarray(chunk, dtype=float)        # shape: (k, 19)
        # → push into the rolling buffer that feeds focus/reward feature extraction
```

**Critical timestamp gotcha (carry over verbatim):** the DSI vendor bridge stamps each *chunk* of samples with nearly-identical wall-clock receive times (microseconds apart within a chunk, then 10–100 ms gaps between chunks). **Do not** use raw LSL timestamps as a per-sample time axis for plotting or for fixed-window feature math — it collapses ~30 samples onto one instant and produces fake "spike" artifacts. Instead synthesize a uniform timeline at the nominal rate:

```python
# n samples in the window, latest sample at t = 0
t_rel = (np.arange(n) - (n - 1)) / srate
```

Keep raw timestamps only for traceability / effective-rate estimation (`samples / wall_span`).

### 8.4 No-hardware development & demos: the simulator

`rlhb-mvp` ships a synthetic LSL publisher that exactly matches the DSI-24 stream shape (`SineWaveSimulator`, selected because the DSI-24 spec is fixed-rate). This is how DopaMAXX runs **without a physical cap** — essential for development on non-Windows machines and as a fallback during demos.

- The simulator advertises a stream with the **same name/type/channels/rate** (`DSI24-EEG`, `EEG`, 19, 300 Hz), so the consumer code in §8.3 is **identical** whether the source is real or simulated.
- The simulator supports **signal injection** (`inject_sinusoid(freq_hz, channel_indices, amplitude, duration_s)`), which overrides specific channels with a known sinusoid. **DopaMAXX's Demo Mode reuses this** to fake EEG states on demand: e.g., inject elevated frontal beta to simulate "focused," or a frontal-alpha pattern to simulate "drifting," or an asymmetry pattern to simulate a "reward hit." (See §9.)

### 8.5 What DopaMAXX needs to build vs. reuse

| Concern | Source | DopaMAXX action |
|---|---|---|
| Launch `dsi2lsl.exe` with correct path/cwd/port | `rlhb` modality launcher + debugging notes | **Reuse pattern**; thin launcher wrapper. |
| Resolve + read `DSI24-EEG` via pylsl | `lsl_utils.py`, `live_view_dsi24.py` | **Reuse pattern.** |
| Ring buffer + reader thread | `live_view_dsi24.py` `_RingBuffer` | **Reuse / port.** |
| Simulator for no-hardware/demo | `acquisition/simulators.py` | **Reuse** (or stand up an equivalent LSL publisher). |
| Focus & reward feature extraction | — (new) | **Build** (§7). |
| Preference model / RAG scoring | Tribe v2 + new glue | **Build** (§7.4). |

---

## 9. Demo Mode (Top Priority)

Demo Mode exists so DopaMAXX can be **live-demoed convincingly** without depending on real-time EEG cooperation, real focus drift, or live Twitter behavior. It must be **deterministic, operator-driven, and visually compelling on a shared screen / stream.**

### 9.1 Manual controls (operator panel)

The operator can, with a click or hotkey:

- **Force mode:** Locked In ↔ Locked Out (overrides the timer).
- **Force timer events:** skip to boundary, freeze/resume timer, trigger a leeway extension.
- **Trigger / stop a microdose** on demand (Locked In).
- **Force an EEG state** (via the simulator's signal injection, §8.4): `Focused`, `Drifting`, `Reward Hit`, `Reward Miss`, `Neutral`. This drives the focus/reward metrics deterministically.
- **Force a post label:** mark the currently displayed post as hit/miss (bypasses EEG) to demonstrate profile learning instantly.
- **Inject a scripted scenario** (see §9.3).

### 9.2 Live dashboard (the screen-shared view)

A single presentable screen showing, live:

1. **EEG strip:** the 19-channel rolling scope (reuse the `live_view_dsi24.py` stacked-channel renderer), with the synthetic-time x-axis from §8.3.
2. **Derived metrics:** live `focus_score` gauge and `reward_score` meter, with thresholds drawn in.
3. **Mode & timer:** current mode, countdown, and a visible indicator when the timer is inside a ±2 min leeway extension ("⏳ extending — flow detected").
4. **Post feed panel:**
   - In **Locked Out:** the post the user is "scrolling," with its live hit/miss verdict and the running tally feeding the profile.
   - In **Locked In / Microdose:** the curated post(s) the agent surfaced, each annotated with its `predicted_reward` and *why* it was chosen (nearest hit-set neighbor / interest cluster).
5. **Preference profile viz:** a simple 2-D projection (e.g., UMAP/PCA) of the hit set, miss set, and the current candidate, so the audience can *see* "this candidate landed near your liked cluster."
6. **Stream link:** the dashboard is designed to be shared via a single link / screen-share (web view), so a remote audience watches EEG + posts update in real time.

### 9.3 Scripted scenarios (one-click demos)

Pre-baked sequences that exercise the full story for an audience:

- **"Drift Rescue":** start Locked In → inject `Drifting` after ~15 s → microdose fires → show 2 curated posts → inject `Reward Hit` → microdose closes → focus restored.
- **"Earned Break":** run Locked In to boundary → inject sustained `Focused` to show the +2 min flow extension → then transition to Locked Out and serve a tailored feed.
- **"Taste Learning":** in Locked Out, scroll N posts with alternating injected hit/miss → watch the preference cluster form → switch to Locked In and show the agent now picking better candidates.

### 9.4 Demo Mode requirements

- Demo Mode must run **end-to-end on the EEG simulator** (no DSI-24 required) **and** transparently on real hardware (operator can mix: real EEG stream + forced labels).
- All injected states must visibly move the on-screen metrics (the audience sees cause→effect).
- Toggling Demo Mode must never require a code change or restart of the EEG stream — it sits *above* the acquisition layer.

---

## 10. Functional Requirements

### 10.1 Acquisition
- **FR-A1:** Launch/teardown the DSI-24 bridge (`dsi2lsl.exe`) with absolute path, correct cwd, and operator-supplied COM port.
- **FR-A2:** Resolve and consume the `DSI24-EEG` LSL stream; recover gracefully if the stream drops.
- **FR-A3:** Surface bridge connection state and the "headset off / power-cycle" failure signature to the UI.
- **FR-A4:** Run identically against the EEG **simulator** when no hardware is present.

### 10.2 Signal processing
- **FR-S1:** Compute a smoothed `focus_score` at ≥1 Hz update rate.
- **FR-S2:** Compute a `reward_score` per dwelled-on post epoch (dwell-gated).
- **FR-S3:** Apply artifact gating (amplitude clip, dead-lead detection).
- **FR-S4:** Run a short onboarding calibration to set per-user baselines/thresholds.

### 10.3 Modes & timer
- **FR-M1:** Implement the Locked In / Locked Out / Microdose state machine (§5).
- **FR-M2:** Implement the adaptive 25/5 timer with ±2 min EEG-aware leeway (§6).
- **FR-M3:** Enforce microdose caps (count, cooldown, per-block ceiling).

### 10.4 Content & preference
- **FR-C1:** Render Twitter/X posts to the user (Locked Out) and surface curated posts (microdose).
- **FR-C2:** Embed posts via Tribe v2; maintain hit/miss sets + interest centroids.
- **FR-C3:** Label each dwelled post hit/miss/neutral from `reward_score` and update the profile online.
- **FR-C4:** Agent scrolls/fetches candidate posts during Locked In and ranks them by `predicted_reward` (similarity to hit set, penalized by miss set).
- **FR-C5:** Persist the preference profile across sessions for the demo user.

### 10.5 Demo
- **FR-D1:** Operator panel with all manual overrides (§9.1).
- **FR-D2:** Live dashboard (§9.2), screen-share/stream friendly.
- **FR-D3:** EEG-state injection via the simulator drives metrics deterministically.
- **FR-D4:** One-click scripted scenarios (§9.3).

---

## 11. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              DopaMAXX                                      │
│                                                                            │
│  ┌────────────┐   LSL (DSI24-EEG, 19ch@300Hz)   ┌──────────────────────┐  │
│  │ DSI-24 cap │ ──► dsi2lsl.exe (Win bridge) ──► │  EEG Acquisition     │  │
│  └────────────┘        OR  EEG Simulator ──────► │  (pylsl inlet +      │  │
│                                                  │   ring buffer)       │  │
│                                                  └──────────┬───────────┘  │
│                                                             ▼              │
│                                              ┌──────────────────────────┐  │
│                                              │  Signal Processing       │  │
│                                              │  focus_score / reward    │  │
│                                              └─────┬───────────────┬────┘  │
│                                                    ▼               ▼       │
│                                   ┌────────────────────┐  ┌────────────────┐
│                                   │  Mode/Timer Engine │  │ Preference     │ │
│                                   │  (state machine +  │  │ Profile +      │ │
│                                   │   adaptive Pomodoro)│  │ Tribe v2 embed │ │
│                                   └─────────┬──────────┘  │ + RAG scoring  │ │
│                                             │             └───────┬────────┘ │
│                                             ▼                     ▼          │
│                                   ┌─────────────────────────────────────┐    │
│                                   │  Content Layer                      │    │
│                                   │  - Locked Out: render user scroll   │    │
│                                   │  - Locked In:  agent fetch+rank      │    │
│                                   │  - Twitter/X integration            │    │
│                                   └──────────────────┬──────────────────┘    │
│                                                      ▼                        │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  UI / Dashboard  (work view, scroll view, Demo Mode operator panel,  │    │
│  │                   live EEG + metrics + post feed; stream/share link)  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

**Suggested stack (proposal, open to change):** Python acquisition/signal/agent core (matches `rlhb`/`pylsl`/NumPy lineage); a web dashboard (so the live view is shareable via a link) talking to the core over a local WebSocket for live EEG/metric/post streaming. The Twitter/X surface and Tribe v2 are integrated behind interfaces so they can be swapped.

---

## 12. Open Questions

1. **Twitter/X access:** Official API (rate limits, post media access, cost) vs. a controlled browser/automation surface for both user scrolling and agent retrieval? What can we legally/technically render and fetch for the demo?
2. **Tribe v2 interface:** Does it return an embedding, a relevance score, or both? Hosting (local vs. API)? Latency budget for scoring agent candidates in real time?
3. **Reward proxy validity:** Is frontal alpha asymmetry + engagement a good enough "did they like it" signal on the DSI-24's dry electrodes, or do we need a per-user learned classifier from day one?
4. **Dwell measurement without eye-tracking:** How do we define "the post the user is looking at" purely from the scroll UI (post in viewport center for ≥ dwell_ms)? (Reminder: no eye-tracking modality in scope.)
5. **Agent scrolling during Locked In:** Does the retrieval agent fetch fresh candidates live, or from a pre-fetched candidate pool refreshed in the background (to keep microdose latency low)?
6. **Persistence/privacy:** EEG + content-preference data is sensitive. What's stored, where, and for how long (especially for a demo build)?
7. **Calibration length vs. demo time:** Can onboarding be compressed enough to run live, or do we ship a pre-calibrated demo-user profile?

---

## 13. Success Metrics (MVP / demo)

- **Demo reliability:** 100% of scripted scenarios run end-to-end on the simulator without manual recovery.
- **Acquisition robustness:** DSI-24 stream comes up within 60 s on a known-good machine; stream-drop is detected and surfaced within 2 s.
- **Latency:** `focus_score` updates ≥1 Hz; microdose fires within `drift_dwell_seconds` of sustained drift; candidate ranking returns within ~1 s.
- **Visible learning:** during a "Taste Learning" demo, the hit cluster visibly forms and the agent's `predicted_reward` for on-cluster posts measurably rises.
- **Qualitative:** in a live work session, microdosing pulls the user back to `focus_score ≥ reengage_threshold` and the flow-extension visibly fires when the user is deeply focused at a boundary.

---

## 14. Milestones (proposed, PRD-level)

1. **M0 — Acquisition spike:** consume `DSI24-EEG` (real + simulator), live 19-ch scope, correct timestamp handling. *(Largely a port from `rlhb-mvp`.)*
2. **M1 — Metrics:** `focus_score` + `reward_score` with onboarding calibration.
3. **M2 — Mode/timer engine:** state machine + adaptive Pomodoro with leeway.
4. **M3 — Content + preference:** Tribe v2 embedding, hit/miss sets, RAG scoring, Locked Out labeling, Locked In agent retrieval + microdose.
5. **M4 — Demo Mode (parallel, prioritized early):** operator panel, live dashboard, simulator state injection, scripted scenarios, shareable stream link.

> Per the brief, **Demo Mode (M4) is prioritized** and should be built incrementally alongside M0–M3 rather than last, so that every milestone is demonstrable on the shared live dashboard from the start.

---

## Appendix A — DSI-24 quick reference (from `rlhb-mvp`)

| Property | Value |
|---|---|
| LSL stream name | `DSI24-EEG` |
| LSL stream type | `EEG` |
| Channels | 19 (10-20 montage) |
| Channel order | `Fp1, Fp2, F7, F3, Fz, F4, F8, T3, C3, Cz, C4, T4, T5, P3, Pz, P4, T6, O1, O2` |
| Sample rate | 300 Hz, fixed |
| Producer | `dsi2lsl.exe --port=<COM> --lsl-stream-name=DSI24-EEG` (Windows-only) |
| Bridge path resolution | `RLHB_DSI_BRIDGE_PATH` (absolute) → config → fallback; launch with `cwd = exe dir` |
| Cold-start | ~12 s; allow 60 s launch timeout + ~3 s settle |
| Failure signature | repeated `Master.DataAcquisitionMode` retries ⇒ headset off → power-cycle |
| Timestamps | batched per-chunk — use synthetic time `(arange(n)-(n-1))/srate`, not raw LSL ts |
| No-hardware path | `SineWaveSimulator` publishes an identical `DSI24-EEG` stream; supports `inject_sinusoid(...)` for forced states |
| Consumer API | `resolve_byprop("name","DSI24-EEG")` → `StreamInlet(info, max_buflen=60)` → `pull_chunk(...)` |

## Appendix B — Glossary

- **Locked In / Locked Out:** Work mode / Play (scroll) mode.
- **Microdose:** A short, EEG-triggered burst of curated posts during Locked In to rescue a drifting user.
- **Hit / Miss:** A post the EEG reward metric labels as rewarding / not.
- **focus_score / reward_score:** EEG-derived engagement and reward proxies.
- **Tribe v2:** Pluggable post-embedding (preference) model; black box in this PRD.
- **RAG framing:** the hit set is the retrieval corpus; candidate posts are scored by similarity to it.
- **Leeway:** ±2 min EEG-aware flexibility around each Pomodoro transition to protect flow.
</content>
</invoke>
