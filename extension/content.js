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
    background: "#e8560a",
    color: "rgba(255,255,255,0.9)",
    fontSize: "9px",
    fontFamily: "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif",
    fontWeight: "600",
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    textAlign: "center",
    padding: "3px 12px",
    pointerEvents: "none",
    userSelect: "none",
  });
  banner.textContent = "Locked In";
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
  if (msg.mode === "locked_in") showLockedInBanner();
  else hideLockedInBanner();
});

chrome.runtime.sendMessage({ type: "get_status" }, (status) => {
  if (status?.mode === "locked_in") showLockedInBanner();
});
