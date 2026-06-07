(function () {
  "use strict";

  const MODE_LOCKED_OUT = "locked_out";
  const SCAN_INTERVAL_MS = 250;
  const SCROLL_IDLE_MS = 300;
  const MIN_DWELL_MS = 7000;
  const CAPTURE_MESSAGE = "locked_out_capture_post";
  const FOR_YOU_CANDIDATES_MESSAGE = "for_you_candidates";
  const STATUS_MESSAGE = "get_status";
  const MODE_CHANGE_MESSAGE = "mode_change";
  const FOR_YOU_SCAN_INTERVAL_MS = 1500;
  const FOR_YOU_BATCH_LIMIT = 30;
  const FOR_YOU_BACKOFF_MS = 30000;
  const LOG_PREFIX = "[DopaMAXX locked-out]";

  if (typeof globalThis.__dopamaxxLockedOutCaptureStop === "function") {
    globalThis.__dopamaxxLockedOutCaptureStop();
  }

  const selector = globalThis.DopaMaxxLockedOutSelector;
  if (!selector) return;

  let currentMode = MODE_LOCKED_OUT;
  let currentWinner = null;
  let currentWinnerSinceMs = 0;
  let scanTimer = null;
  let forYouScanTimer = null;
  let scanQueued = false;
  let forYouScanQueued = false;
  let lastScrollAtMs = 0;
  let forYouPausedUntilMs = 0;
  let forYouLastBackendWarnAtMs = -FOR_YOU_BACKOFF_MS;
  const submittedPostIds = new Set();
  const submittedForYouPostIds = new Set();
  const inflightForYouPostIds = new Set();

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
    console.debug(`${LOG_PREFIX} active`, {
      mode: currentMode,
      scan_interval_ms: SCAN_INTERVAL_MS,
      scroll_idle_ms: SCROLL_IDLE_MS,
      min_dwell_ms: MIN_DWELL_MS,
    });
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

  function startForYouBuffering() {
    if (forYouScanTimer) return;
    forYouScanTimer = window.setInterval(queueForYouScan, FOR_YOU_SCAN_INTERVAL_MS);
    window.addEventListener("scroll", queueForYouScan, { passive: true });
    window.addEventListener("resize", queueForYouScan, { passive: true });
    queueForYouScan();
  }

  function stopForYouBuffering() {
    if (forYouScanTimer) {
      window.clearInterval(forYouScanTimer);
      forYouScanTimer = null;
    }
    window.removeEventListener("scroll", queueForYouScan);
    window.removeEventListener("resize", queueForYouScan);
  }

  function handleScroll() {
    lastScrollAtMs = performance.now();
    currentWinner = null;
    currentWinnerSinceMs = 0;
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

  function queueForYouScan() {
    if (!shouldCollectForYouCandidates() || forYouScanQueued) return;
    if (performance.now() < forYouPausedUntilMs) return;
    forYouScanQueued = true;
    window.requestAnimationFrame(() => {
      forYouScanQueued = false;
      scanForYouCandidates();
    });
  }

  function scan() {
    if (!shouldCapture()) return;

    const nowMs = performance.now();
    if (!isScrollIdle(nowMs)) return;

    const candidates = collectTweetCandidates();
    const winner = selector.pickCenteredPost(candidates, window.innerHeight);

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
        viewport_coverage: winner.viewportCoverage,
        eligibility: winner.eligibility,
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
    currentWinner.viewport_coverage = winner.viewportCoverage;
    currentWinner.eligibility = winner.eligibility;
    currentWinner.rect = rectToJson(winner.candidate.rect);

    if (dwellMs < MIN_DWELL_MS) return;
    if (submittedPostIds.has(post.platform_post_id)) return;

    submittedPostIds.add(post.platform_post_id);
    submitCapture({
      post,
      dwell_ms: Math.round(dwellMs),
      detection_to_capture_ms: Math.round(nowMs - currentWinnerSinceMs),
      scroll_idle_before_detection_ms: lastScrollAtMs > 0
        ? Math.round(currentWinnerSinceMs - lastScrollAtMs)
        : null,
      viewport_score: Number(winner.score.toFixed(4)),
      center_score: Number(winner.centerScore.toFixed(4)),
      main_visible_ratio: Number(winner.mainVisibleRatio.toFixed(4)),
      viewport_coverage: Number(winner.viewportCoverage.toFixed(4)),
      eligibility: winner.eligibility,
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
          scroll_idle_ms: SCROLL_IDLE_MS,
          duplicate_policy: "once_per_post_per_tab_session",
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

  function scanForYouCandidates() {
    if (!shouldCollectForYouCandidates()) return;

    const candidates = collectTweetCandidates()
      .sort((a, b) => a.rect.top - b.rect.top)
      .map((candidate) => candidate.post)
      .filter((post) => {
        const postId = post && post.platform_post_id;
        return postId
          && !submittedForYouPostIds.has(postId)
          && !inflightForYouPostIds.has(postId);
      })
      .slice(0, FOR_YOU_BATCH_LIMIT);

    if (!candidates.length) return;
    submitForYouCandidates(candidates);
  }

  function shouldCollectForYouCandidates() {
    if (!isSupportedHost()) return false;
    if (window.location.pathname !== "/home") return false;
    return isForYouTabSelected();
  }

  function isForYouTabSelected() {
    const tabs = Array.from(
      document.querySelectorAll('[role="tab"][aria-selected="true"], a[aria-selected="true"]')
    );
    if (!tabs.length) return true;

    const selectedText = tabs
      .map((tab) => cleanText(tab.innerText || tab.getAttribute("aria-label") || "").toLowerCase())
      .join(" ");
    if (selectedText.includes("following")) return false;
    if (selectedText.includes("for you")) return true;
    return true;
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

  function submitCapture(capture) {
    const sentAtMs = performance.now();
    console.debug(`${LOG_PREFIX} capture-submit`, {
      post_id: capture.post.platform_post_id,
      author: capture.post.author_handle,
      dwell_ms: capture.dwell_ms,
      detection_to_capture_ms: capture.detection_to_capture_ms,
      scroll_idle_before_detection_ms: capture.scroll_idle_before_detection_ms,
      viewport_score: capture.viewport_score,
      main_visible_ratio: capture.main_visible_ratio,
      viewport_coverage: capture.viewport_coverage,
      eligibility: capture.eligibility,
    });

    try {
      chrome.runtime.sendMessage({ type: CAPTURE_MESSAGE, capture }, (response) => {
        const extensionRoundTripMs = Math.round(performance.now() - sentAtMs);
        if (chrome.runtime.lastError) {
          console.warn(`${LOG_PREFIX} capture-error`, {
            post_id: capture.post.platform_post_id,
            extension_round_trip_ms: extensionRoundTripMs,
            error: chrome.runtime.lastError.message,
          });
          return;
        }
        if (!response || !response.ok) {
          console.warn(`${LOG_PREFIX} capture-rejected`, {
            post_id: capture.post.platform_post_id,
            extension_round_trip_ms: extensionRoundTripMs,
            error: response && response.error,
          });
          return;
        }

        console.log(`${LOG_PREFIX} capture-saved`, {
          post_id: capture.post.platform_post_id,
          author: capture.post.author_handle,
          dwell_ms: capture.dwell_ms,
          scroll_idle_before_detection_ms: capture.scroll_idle_before_detection_ms,
          eligibility: capture.eligibility,
          viewport_coverage: capture.viewport_coverage,
          extension_round_trip_ms: extensionRoundTripMs,
          supabase_round_trip_ms: response.supabase_round_trip_ms,
          reward_label: response.reward_label,
          reward_score: response.reward_score,
          focus_score: response.focus_score,
          reward_source: response.reward_source,
          embedding_status: response.embedding_status,
          embedding_async: response.embedding_async,
          observation_id: response.observation_id,
        });
      });
    } catch (error) {
      stop();
      console.warn(`${LOG_PREFIX} extension-context-invalidated`, {
        post_id: capture.post.platform_post_id,
        error: error && error.message ? error.message : String(error),
        action: "reload the X tab after reloading the unpacked extension",
      });
    }
  }

  function submitForYouCandidates(posts) {
    const observedAt = new Date().toISOString();
    for (const post of posts) inflightForYouPostIds.add(post.platform_post_id);

    try {
      chrome.runtime.sendMessage(
        {
          type: FOR_YOU_CANDIDATES_MESSAGE,
          posts,
          observed_at: observedAt,
          source_url: window.location.href,
        },
        (response) => {
          for (const post of posts) inflightForYouPostIds.delete(post.platform_post_id);
          if (chrome.runtime.lastError || !response || !response.ok) {
            handleForYouCandidateError(posts.length, chrome.runtime.lastError
              ? chrome.runtime.lastError.message
              : response && response.error, response);
            return;
          }

          forYouPausedUntilMs = 0;
          for (const post of posts) submittedForYouPostIds.add(post.platform_post_id);
          console.debug(`${LOG_PREFIX} for-you-candidates-buffered`, {
            count: posts.length,
            buffered_count: response.buffered_count,
          });
        }
      );
    } catch (error) {
      for (const post of posts) inflightForYouPostIds.delete(post.platform_post_id);
      handleForYouCandidateError(posts.length, error && error.message ? error.message : String(error), null);
    }
  }

  function handleForYouCandidateError(count, error, response) {
    const message = String(error || "unknown error");
    if (isBackendUnavailable(message, response)) {
      const nowMs = performance.now();
      forYouPausedUntilMs = nowMs + FOR_YOU_BACKOFF_MS;
      if (nowMs - forYouLastBackendWarnAtMs >= FOR_YOU_BACKOFF_MS) {
        forYouLastBackendWarnAtMs = nowMs;
        console.warn(`${LOG_PREFIX} for-you-candidates-paused`, {
          count,
          error: message,
          backend_url: response && response.backend_url,
          retry_in_ms: FOR_YOU_BACKOFF_MS,
        });
      }
      return;
    }

    console.warn(`${LOG_PREFIX} for-you-candidates-rejected`, {
      count,
      error: message,
    });
  }

  function isBackendUnavailable(message, response) {
    return Boolean(response && response.backend_unavailable) ||
      message.includes("Failed to fetch") ||
      message.includes("NetworkError") ||
      message.includes("Load failed");
  }

  function logCandidateDetected(winner, nowMs) {
    const msSinceScroll = lastScrollAtMs > 0 ? Math.round(nowMs - lastScrollAtMs) : null;
    console.debug(`${LOG_PREFIX} centered-post-detected`, {
      post_id: winner.post.platform_post_id,
      author: winner.post.author_handle,
      ms_since_scroll: msSinceScroll,
      viewport_score: Number(winner.score.toFixed(4)),
      center_score: Number(winner.center_score.toFixed(4)),
      main_visible_ratio: Number(winner.main_visible_ratio.toFixed(4)),
      viewport_coverage: Number(winner.viewport_coverage.toFixed(4)),
      eligibility: winner.eligibility,
      scroll_idle_ms: lastScrollAtMs > 0 ? Math.round(nowMs - lastScrollAtMs) : null,
      text_preview: String(winner.post.text || "").slice(0, 120),
    });
  }

  function isScrollIdle(nowMs) {
    return lastScrollAtMs === 0 || nowMs - lastScrollAtMs >= SCROLL_IDLE_MS;
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

  globalThis.__dopamaxxLockedOutCaptureStop = () => {
    stop();
    stopForYouBuffering();
  };

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
    startForYouBuffering();
  });
})();
