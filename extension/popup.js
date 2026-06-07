const modeName   = document.getElementById("modeName");
const timerVal   = document.getElementById("timerVal");
const focusVal   = document.getElementById("focusVal");
const rewardVal  = document.getElementById("rewardVal");
const eegDot     = document.getElementById("eegDot");
const eegTxt     = document.getElementById("eegTxt");
const switchBtn  = document.getElementById("switchBtn");
const demoToggle = document.getElementById("demoToggle");

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

  eegDot.className = "live-dot" + (s.wsConnected ? " on" : "");
  eegTxt.textContent = s.wsConnected ? "live" : "offline";

  demoToggle.checked  = s.demoMode;
  switchBtn.disabled  = !s.demoMode;

  if (s.demoMode) {
    switchBtn.textContent = locked ? "Switch to Locked Out" : "Switch to Locked In";
    switchBtn.className   = "btn armed";
  } else {
    switchBtn.textContent = "Switch Mode";
    switchBtn.className   = "btn";
  }
}

chrome.runtime.sendMessage({ type: "get_status" }, (s) => { if (s) render(s); });
chrome.runtime.onMessage.addListener((msg) => { if (msg.type === "status_update") render(msg); });

demoToggle.addEventListener("change", () => {
  chrome.runtime.sendMessage({ type: "set_demo_mode", enabled: demoToggle.checked }, (s) => { if (s) render(s); });
});

switchBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "demo_toggle_mode" }, (s) => { if (s) render(s); });
});
