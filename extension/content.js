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
    background: "rgba(0,0,0,0.45)",
    backdropFilter: "blur(12px) saturate(1.4)",
    webkitBackdropFilter: "blur(12px) saturate(1.4)",
    color: "rgba(255,255,255,0.65)",
    fontSize: "10px",
    fontFamily: "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif",
    fontWeight: "600",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    textAlign: "center",
    padding: "7px 12px",
    pointerEvents: "none",
    userSelect: "none",
    borderBottom: "1px solid rgba(255,255,255,0.08)",
  });
  banner.textContent = "DopaMAXX — Locked In";
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
