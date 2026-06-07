let banner = null;

function getPageColor() {
  // Prefer the page body/root — we want to blend with the page, not the header chrome
  const primary = [document.body, document.documentElement];
  for (const el of primary) {
    if (!el) continue;
    const rgba = parseRgba(getComputedStyle(el).backgroundColor);
    if (rgba && rgba.a > 0.1 && !isWhiteOrTransparent(rgba)) {
      return rgba;
    }
  }

  // Only fall back to structural elements if the body is transparent/white
  const fallbacks = [
    document.querySelector("main"),
    document.querySelector('[role="main"]'),
    document.querySelector("#root"),
    document.querySelector("#app"),
  ];
  for (const el of fallbacks) {
    if (!el) continue;
    const rgba = parseRgba(getComputedStyle(el).backgroundColor);
    if (rgba && rgba.a > 0.1 && !isWhiteOrTransparent(rgba)) {
      return rgba;
    }
  }

  return { r: 20, g: 20, b: 20, a: 1 };
}

function parseRgba(str) {
  if (!str) return null;
  const m = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
  if (!m) return null;
  return { r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1 };
}

function isWhiteOrTransparent({ r, g, b, a }) {
  if (a < 0.1) return true;
  // Very light (near-white) — also treat as transparent for our purposes
  const luminance = (r * 299 + g * 587 + b * 114) / 1000;
  return luminance > 235;
}

function luminance({ r, g, b }) {
  return (r * 299 + g * 587 + b * 114) / 1000;
}

function darken({ r, g, b }, amount = 0.75) {
  return {
    r: Math.round(r * amount),
    g: Math.round(g * amount),
    b: Math.round(b * amount),
  };
}

function toRgb({ r, g, b }) {
  return `rgb(${r},${g},${b})`;
}

function showLockedInBanner() {
  if (banner) return;

  const color = getPageColor();
  const darkened = darken(color);
  const bg = toRgb(darkened);
  const textColor = luminance(darkened) > 128 ? "rgba(0,0,0,0.75)" : "rgba(255,255,255,0.75)";

  banner = document.createElement("div");
  banner.id = "__dopamaxx_banner";
  Object.assign(banner.style, {
    position: "fixed",
    top: "0",
    left: "0",
    right: "0",
    zIndex: "2147483647",
    background: bg,
    color: textColor,
    fontSize: "10px",
    fontFamily: "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif",
    fontWeight: "600",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    textAlign: "center",
    padding: "7px 12px",
    pointerEvents: "none",
    userSelect: "none",
    borderBottom: `1px solid rgba(255,255,255,0.08)`,
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
