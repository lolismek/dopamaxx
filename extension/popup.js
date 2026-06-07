const modeTag    = document.getElementById("modeTag");
const timerEl    = document.getElementById("timer");
const eegBadge   = document.getElementById("eegBadge");
const eegLabel   = document.getElementById("eegLabel");
const focusVal   = document.getElementById("focusVal");
const rewardVal  = document.getElementById("rewardVal");
const switchBtn  = document.getElementById("switchBtn");
const demoToggle = document.getElementById("demoToggle");
const demoText   = document.getElementById("demoText");
const demoNote   = document.getElementById("demoNote");

function fmt(seconds) {
  if (seconds == null || seconds === 0) return "--:--";
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function applyStatus(s) {
  const isLockedIn = s.mode === "locked_in";

  modeTag.textContent = isLockedIn ? "LOCKED IN" : "LOCKED OUT";
  modeTag.className   = "mode-tag " + (isLockedIn ? "locked-in" : "locked-out");

  timerEl.textContent = fmt(s.timerSeconds);
  timerEl.className   = "timer" + (s.timerSeconds ? "" : " dim");

  if (s.wsConnected) {
    eegBadge.className = "eeg-badge live";
    eegLabel.textContent = "EEG LIVE";
  } else {
    eegBadge.className = "eeg-badge";
    eegLabel.textContent = "EEG OFFLINE";
  }

  focusVal.textContent  = s.focusScore  != null ? s.focusScore.toFixed(2)  : "—";
  rewardVal.textContent = s.rewardScore != null ? s.rewardScore.toFixed(2) : "—";

  demoToggle.checked  = s.demoMode;
  demoText.textContent = s.demoMode ? "ON" : "OFF";
  switchBtn.disabled   = !s.demoMode;

  if (s.demoMode) {
    switchBtn.textContent = isLockedIn ? "SWITCH TO LOCKED OUT" : "SWITCH TO LOCKED IN";
    switchBtn.className   = "switch-btn " + (isLockedIn ? "to-locked-out" : "to-locked-in");
    demoNote.textContent  = "eeg signals ignored — manual override active";
  } else {
    switchBtn.textContent = isLockedIn ? "SWITCH TO LOCKED OUT" : "SWITCH TO LOCKED IN";
    switchBtn.className   = "switch-btn";
    demoNote.textContent  = "enable demo mode to override eeg transitions";
  }
}

chrome.runtime.sendMessage({ type: "get_status" }, (s) => { if (s) applyStatus(s); });

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "status_update") applyStatus(msg);
});

demoToggle.addEventListener("change", () => {
  chrome.runtime.sendMessage({ type: "set_demo_mode", enabled: demoToggle.checked }, (s) => {
    if (s) applyStatus(s);
  });
});

switchBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "demo_toggle_mode" }, (s) => {
    if (s) applyStatus(s);
  });
});
