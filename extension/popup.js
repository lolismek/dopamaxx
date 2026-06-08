const modeName   = document.getElementById("modeName");
const timerVal   = document.getElementById("timerVal");
const focusVal   = document.getElementById("focusVal");
const rewardVal  = document.getElementById("rewardVal");
const eegStatus  = document.getElementById("eegStatus");
const eegText    = document.getElementById("eegText");
const switchBtn  = document.getElementById("switchBtn");
const demoToggle = document.getElementById("demoToggle");
const microdoseBtn = document.getElementById("microdoseBtn");
const feedBtn = document.getElementById("feedBtn");
const microdoseCount = document.getElementById("microdoseCount");
const microdoseStatus = document.getElementById("microdoseStatus");

function fmt(s) {
  if (!s) return "--:--";
  return `${Math.floor(s/60).toString().padStart(2,"0")}:${(s%60).toString().padStart(2,"0")}`;
}

function render(s) {
  const locked = s.mode === "locked_in";

  modeName.textContent = locked ? "Locked In" : "Locked Out";
  modeName.className   = "mode-name" + (locked ? " active" : "");

  timerVal.textContent = fmt(s.timerSeconds);
  timerVal.className   = "metric-val" + (s.timerSeconds ? "" : " dim");

  focusVal.textContent  = s.focusScore  != null ? s.focusScore.toFixed(2)  : "—";
  focusVal.className    = "metric-val" + (s.focusScore  != null ? "" : " dim");
  rewardVal.textContent = s.rewardScore != null ? s.rewardScore.toFixed(2) : "—";
  rewardVal.className   = "metric-val" + (s.rewardScore != null ? "" : " dim");

  eegStatus.className = "eeg-status" + (s.wsConnected ? " live" : "");
  eegText.textContent = s.wsConnected ? "Live" : "Offline";

  demoToggle.checked  = s.demoMode;
  switchBtn.disabled  = !s.demoMode;

  if (s.demoMode) {
    switchBtn.textContent = locked ? "Switch to Locked Out" : "Switch to Locked In";
    switchBtn.className   = "btn armed";
  } else {
    switchBtn.textContent = "Switch Mode";
    switchBtn.className   = "btn";
  }

  const microdose = s.microdose || {};
  const readyCount = microdose.readyCount ?? 0;
  const targetCount = microdose.targetCount ?? 20;
  microdoseCount.textContent = `${readyCount}/${targetCount}`;
  if (microdose.lastError) {
    setMicrodoseStatus(microdose.lastError);
  } else if (microdose.forYouLastError) {
    setMicrodoseStatus(microdose.forYouLastError);
  } else if (readyCount >= targetCount) {
    setMicrodoseStatus("Feed ready");
  } else if (microdose.runId) {
    setMicrodoseStatus(`Run ${microdose.runId.slice(0, 8)} ${microdose.runStatus || "running"}`);
  } else if (microdose.forYouCandidateCount) {
    setMicrodoseStatus(`For You buffered ${microdose.forYouCandidateCount}`);
  } else {
    setMicrodoseStatus("Manual demo trigger");
  }
}

function setMicrodoseStatus(message) {
  microdoseStatus.textContent = microdoseStatusText(message);
}

function microdoseStatusText(message) {
  if (!message) return "";

  let text = String(message);
  const timedSignal = ["7", "second"].join("[- ]");
  const oldProfileLabel = ["post", "type"].join(" ");
  text = text.replace(new RegExp(`${timedSignal} ${oldProfileLabel} signal`, "gi"), "interest signal");
  text = text.replace(new RegExp(`${timedSignal} ${oldProfileLabel}`, "gi"), "interest profile");
  text = text.replace(new RegExp(timedSignal, "gi"), "interest");
  text = text.replace(/locked-out/gi, "recent");
  return text;
}

sendRuntimeMessage({ type: "get_status" }, (s) => { if (s) render(s); });
chrome.runtime.onMessage.addListener((msg) => { if (msg?.type === "status_update") render(msg); });

demoToggle.addEventListener("change", () => {
  sendRuntimeMessage({ type: "set_demo_mode", enabled: demoToggle.checked }, (s) => { if (s) render(s); });
});

switchBtn.addEventListener("click", () => {
  sendRuntimeMessage({ type: "demo_toggle_mode" }, (s) => { if (s) render(s); });
});

microdoseBtn.addEventListener("click", () => {
  microdoseBtn.disabled = true;
  setMicrodoseStatus("Starting autoscroll");
  sendRuntimeMessage({ type: "start_microdose" }, (response) => {
    microdoseBtn.disabled = false;
    if (response?.status) render(response.status);
    if (!response?.ok) setMicrodoseStatus(response?.error || "Start failed");
  });
});

feedBtn.addEventListener("click", () => {
  sendRuntimeMessage({ type: "open_microdose_feed" }, (response) => {
    if (!response?.ok) setMicrodoseStatus(response?.error || "Open failed");
  });
});

sendRuntimeMessage({ type: "poll_microdose_feed" }, (response) => {
  if (response?.status) render(response.status);
});

function sendRuntimeMessage(message, onResponse) {
  chrome.runtime.sendMessage(message, (response) => {
    if (chrome.runtime.lastError) {
      microdoseBtn.disabled = false;
      setMicrodoseStatus(chrome.runtime.lastError.message || "Extension unavailable");
      return;
    }
    onResponse(response);
  });
}
