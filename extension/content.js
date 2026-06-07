// Receives mode changes from background and shows/hides the overlay banner.

let banner = null;

function showLockedInBanner() {
  if (banner) return;
  banner = document.createElement("div");
  banner.id = "__dopamaxx_banner";
  Object.assign(banner.style, {
    position: "fixed",
    top: "0",
    left: "0",
    right: "0",
    zIndex: "2147483647",
    background: "linear-gradient(90deg, #3b0764, #4c1d95)",
    color: "#e9d5ff",
    fontSize: "13px",
    fontFamily: "system-ui, sans-serif",
    fontWeight: "600",
    letterSpacing: "0.06em",
    textAlign: "center",
    padding: "7px 12px",
    pointerEvents: "none",
    userSelect: "none",
  });
  banner.textContent = "🔒 DOPAMAXX — LOCKED IN. STAY FOCUSED.";
  document.documentElement.appendChild(banner);
}

function hideLockedInBanner() {
  if (banner) {
    banner.remove();
    banner = null;
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== "mode_change") return;
  if (msg.mode === "locked_in") {
    showLockedInBanner();
  } else {
    hideLockedInBanner();
  }
});

// Ask background for current mode on page load
chrome.runtime.sendMessage({ type: "get_status" }, (status) => {
  if (!status) return;
  if (status.mode === "locked_in") showLockedInBanner();
});
