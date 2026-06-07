const modePill  = document.getElementById("modePill");
const timerEl   = document.getElementById("timer");
const wsBadge   = document.getElementById("wsBadge");
const switchBtn = document.getElementById("switchBtn");
const demoToggle = document.getElementById("demoToggle");
const demoLabel = document.getElementById("demoLabel");
const demoNote  = document.getElementById("demoNote");

function formatTime(seconds) {
  if (!seconds && seconds !== 0) return "—";
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function applyStatus(status) {
  const isLockedIn = status.mode === "locked_in";

  modePill.textContent = isLockedIn ? "LOCKED IN" : "LOCKED OUT";
  modePill.className = "mode-pill " + (isLockedIn ? "locked-in" : "locked-out");

  timerEl.textContent = formatTime(status.timerSeconds);

  if (status.wsConnected) {
    wsBadge.textContent = "EEG live";
    wsBadge.className = "ws-badge connected";
  } else {
    wsBadge.textContent = "EEG offline";
    wsBadge.className = "ws-badge disconnected";
  }

  demoToggle.checked = status.demoMode;
  demoLabel.textContent = status.demoMode ? "on" : "off";
  switchBtn.disabled = !status.demoMode;

  if (status.demoMode) {
    switchBtn.textContent = isLockedIn ? "Switch to LOCKED OUT" : "Switch to LOCKED IN";
    switchBtn.className = "demo-btn " + (isLockedIn ? "to-locked-out" : "to-locked-in");
    demoNote.textContent = "Manual override active — EEG signals ignored";
  } else {
    demoNote.textContent = "Enable demo mode to manually control transitions";
  }
}

// Load initial status
chrome.runtime.sendMessage({ type: "get_status" }, (status) => {
  if (status) applyStatus(status);
});

// Live updates from background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "status_update") applyStatus(msg);
});

// Demo mode toggle
demoToggle.addEventListener("change", () => {
  chrome.runtime.sendMessage(
    { type: "set_demo_mode", enabled: demoToggle.checked },
    (status) => { if (status) applyStatus(status); }
  );
});

// Switch mode button
switchBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "demo_toggle_mode" }, (status) => {
    if (status) applyStatus(status);
  });
});
