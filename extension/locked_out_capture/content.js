(function () {
  "use strict";

  const MODE_LOCKED_OUT = "locked_out";
  const SCAN_INTERVAL_MS = 250;
  const MIN_DWELL_MS = 1200;
  const DUPLICATE_SUPPRESSION_MS = 60000;
  const CAPTURE_MESSAGE = "locked_out_capture_post";
  const STATUS_MESSAGE = "get_status";
  const MODE_CHANGE_MESSAGE = "mode_change";
  const LOG_PREFIX = "[DopaMAXX locked-out]";

  const selector = globalThis.DopaMaxxLockedOutSelector;
  if (!selector) return;

  let currentMode = MODE_LOCKED_OUT;
  let currentWinner = null;
  let currentWinnerSinceMs = 0;
  let scanTimer = null;
  let scanQueued = false;
  let lastScrollAtMs = 0;
  const submittedAtByPostId = new Map();

  function isSupportedHost() {
    const host = window.location.hostname.replace(/^www\./, "");
    return host === "x.com" || host === "twitter.com";
  }

  function shouldCapture() {
    return isSupportedHost() && currentMode === MODE_LOCKED_OUT;
  }

  function start() {
    if (scanTimer) return;
    scanTimer = window.setInterval(queueScan, SCAN_INTERVAL_MS);
    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("resize", queueScan, { passive: true });
    queueScan();
  }

  function stop() {
    if (scanTimer) {
      window.clearInterval(scanTimer);
      scanTimer = null;
    }
    window.removeEventListener("scroll", handleScroll);
    window.removeEventListener("resize", queueScan);
    currentWinner = null;
    currentWinnerSinceMs = 0;
  }

  function handleScroll() {
    lastScrollAtMs = performance.now();
    queueScan();
  }

  function queueScan() {
    if (!shouldCapture() || scanQueued) return;
    scanQueued = true;
    window.requestAnimationFrame(() => {
      scanQueued = false;
      scan();
    });
  }

  function scan() {
    if (!shouldCapture()) return;

    const candidates = collectTweetCandidates();
    const winner = selector.pickCenteredPost(candidates, window.innerHeight);
    const nowMs = performance.now();

    if (!winner) {
      currentWinner = null;
      currentWinnerSinceMs = 0;
      return;
    }

    const post = winner.candidate.post;
    if (!post || !post.platform_post_id) {
      currentWinner = null;
      currentWinnerSinceMs = 0;
      return;
    }

    if (!currentWinner || currentWinner.post.platform_post_id !== post.platform_post_id) {
      currentWinner = {
        post,
        score: winner.score,
        center_score: winner.centerScore,
        main_visible_ratio: winner.mainVisibleRatio,
        rect: rectToJson(winner.candidate.rect),
      };
      currentWinnerSinceMs = nowMs;
      logCandidateDetected(currentWinner, nowMs);
      return;
    }

    const dwellMs = nowMs - currentWinnerSinceMs;
    currentWinner.score = winner.score;
    currentWinner.center_score = winner.centerScore;
    currentWinner.main_visible_ratio = winner.mainVisibleRatio;
    currentWinner.rect = rectToJson(winner.candidate.rect);

    if (dwellMs < MIN_DWELL_MS) return;
    if (wasRecentlySubmitted(post.platform_post_id, nowMs)) return;

    submittedAtByPostId.set(post.platform_post_id, nowMs);
    submitCapture({
      post,
      dwell_ms: Math.round(dwellMs),
      detection_to_capture_ms: Math.round(nowMs - currentWinnerSinceMs),
      viewport_score: Number(winner.score.toFixed(4)),
      center_score: Number(winner.centerScore.toFixed(4)),
      main_visible_ratio: Number(winner.mainVisibleRatio.toFixed(4)),
      observed_at: new Date().toISOString(),
      raw_capture: {
        url: window.location.href,
        title: document.title,
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight,
          scroll_y: window.scrollY,
        },
        rect: currentWinner.rect,
        detection: {
          min_dwell_ms: MIN_DWELL_MS,
          duplicate_suppression_ms: DUPLICATE_SUPPRESSION_MS,
          selector_version: "centered_post_v1",
        },
      },
    });
  }

  function collectTweetCandidates() {
    const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const candidates = [];

    for (const article of articles) {
      const post = extractPost(article);
      if (!post) continue;
      const rect = article.getBoundingClientRect();
      candidates.push({ rect, post });
    }

    return candidates;
  }

  function extractPost(article) {
    const statusLink = findStatusLink(article);
    if (!statusLink) return null;

    let url;
    try {
      url = new URL(statusLink.href, window.location.origin);
    } catch {
      return null;
    }

    const match = url.pathname.match(/^\/([^/]+)\/status\/(\d+)/);
    if (!match) return null;

    const authorHandle = match[1];
    const platformPostId = match[2];
    const canonicalUrl = `https://x.com/${authorHandle}/status/${platformPostId}`;
    const tweetText = article.querySelector('[data-testid="tweetText"]');
    const userName = article.querySelector('[data-testid="User-Name"]');

    return {
      platform: "x",
      platform_post_id: platformPostId,
      canonical_url: canonicalUrl,
      author_handle: authorHandle,
      author_name: cleanAuthorName(userName ? userName.innerText : ""),
      text: cleanText(tweetText ? tweetText.innerText : article.innerText || ""),
      media: extractMedia(article),
    };
  }

  function findStatusLink(article) {
    const links = Array.from(article.querySelectorAll('a[href*="/status/"]'));
    return links.find((link) => {
      try {
        const url = new URL(link.href, window.location.origin);
        return /^\/[^/]+\/status\/\d+/.test(url.pathname);
      } catch {
        return false;
      }
    });
  }

  function cleanAuthorName(value) {
    const lines = cleanText(value).split("\n").map((line) => line.trim()).filter(Boolean);
    return lines.find((line) => !line.startsWith("@")) || "";
  }

  function cleanText(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function extractMedia(article) {
    const media = [];
    const seen = new Set();
    const images = article.querySelectorAll('[data-testid="tweetPhoto"] img, img[alt][src*="twimg.com/media"]');

    for (const image of images) {
      const src = image.currentSrc || image.src;
      if (!src || seen.has(src)) continue;
      seen.add(src);
      media.push({
        type: "image",
        src,
        alt: image.alt || "",
      });
    }

    const videos = article.querySelectorAll("video");
    for (const video of videos) {
      const poster = video.poster || "";
      const key = poster || `video-${media.length}`;
      if (seen.has(key)) continue;
      seen.add(key);
      media.push({
        type: "video",
        poster,
        alt: video.getAttribute("aria-label") || "",
      });
    }

    return media;
  }

  function wasRecentlySubmitted(postId, nowMs) {
    const submittedAt = submittedAtByPostId.get(postId);
    return typeof submittedAt === "number" && nowMs - submittedAt < DUPLICATE_SUPPRESSION_MS;
  }

  function submitCapture(capture) {
    const sentAtMs = performance.now();
    console.log(`${LOG_PREFIX} capture-submit`, {
      post_id: capture.post.platform_post_id,
      author: capture.post.author_handle,
      dwell_ms: capture.dwell_ms,
      detection_to_capture_ms: capture.detection_to_capture_ms,
      viewport_score: capture.viewport_score,
      main_visible_ratio: capture.main_visible_ratio,
    });

    chrome.runtime.sendMessage({ type: CAPTURE_MESSAGE, capture }, (response) => {
      const extensionRoundTripMs = Math.round(performance.now() - sentAtMs);
      if (chrome.runtime.lastError) {
        console.log(`${LOG_PREFIX} capture-error`, {
          post_id: capture.post.platform_post_id,
          extension_round_trip_ms: extensionRoundTripMs,
          error: chrome.runtime.lastError.message,
        });
        return;
      }
      if (!response || !response.ok) {
        console.log(`${LOG_PREFIX} capture-rejected`, {
          post_id: capture.post.platform_post_id,
          extension_round_trip_ms: extensionRoundTripMs,
          error: response && response.error,
        });
        return;
      }

      console.log(`${LOG_PREFIX} capture-saved`, {
        post_id: capture.post.platform_post_id,
        extension_round_trip_ms: extensionRoundTripMs,
        supabase_round_trip_ms: response.supabase_round_trip_ms,
        reward_label: response.reward_label,
        reward_score: response.reward_score,
        embedding_status: response.embedding_status,
        observation_id: response.observation_id,
      });
    });
  }

  function logCandidateDetected(winner, nowMs) {
    const msSinceScroll = lastScrollAtMs > 0 ? Math.round(nowMs - lastScrollAtMs) : null;
    console.log(`${LOG_PREFIX} centered-post-detected`, {
      post_id: winner.post.platform_post_id,
      author: winner.post.author_handle,
      ms_since_scroll: msSinceScroll,
      viewport_score: Number(winner.score.toFixed(4)),
      center_score: Number(winner.center_score.toFixed(4)),
      main_visible_ratio: Number(winner.main_visible_ratio.toFixed(4)),
      text_preview: String(winner.post.text || "").slice(0, 120),
    });
  }

  function rectToJson(rect) {
    return {
      top: Math.round(rect.top),
      bottom: Math.round(rect.bottom),
      left: Math.round(rect.left),
      right: Math.round(rect.right),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || msg.type !== MODE_CHANGE_MESSAGE) return;
    currentMode = msg.mode;
    if (shouldCapture()) {
      start();
    } else {
      stop();
    }
  });

  chrome.runtime.sendMessage({ type: STATUS_MESSAGE }, (status) => {
    if (chrome.runtime.lastError) return;
    currentMode = status && status.mode ? status.mode : MODE_LOCKED_OUT;
    if (shouldCapture()) start();
  });
})();
