(function (root) {
  "use strict";

  const DEFAULT_OPTIONS = Object.freeze({
    minMainVisibleRatio: 0.65,
    centerBandRatio: 0.5,
    centerWeight: 0.65,
    visibilityWeight: 0.35,
    ambiguityMargin: 0.08,
  });

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function scoreCandidate(candidate, viewportHeight, options) {
    const rect = candidate.rect;
    if (!rect || viewportHeight <= 0) return null;

    const height = Math.max(Number(rect.height) || 0, Number(rect.bottom) - Number(rect.top));
    if (height <= 0) return null;

    const visibleTop = clamp(Number(rect.top), 0, viewportHeight);
    const visibleBottom = clamp(Number(rect.bottom), 0, viewportHeight);
    const visibleHeight = Math.max(0, visibleBottom - visibleTop);
    if (visibleHeight <= 0) return null;

    const denominator = Math.max(1, Math.min(height, viewportHeight));
    const mainVisibleRatio = visibleHeight / denominator;
    if (mainVisibleRatio < options.minMainVisibleRatio) return null;

    const centerY = Number(rect.top) + height / 2;
    const viewportCenterY = viewportHeight / 2;
    const centerDistance = Math.abs(centerY - viewportCenterY) / viewportCenterY;
    const centerScore = 1 - clamp(centerDistance, 0, 1);

    const maxCenterDistance = options.centerBandRatio / 2;
    if (centerDistance > maxCenterDistance) return null;

    const score =
      options.centerWeight * centerScore +
      options.visibilityWeight * clamp(mainVisibleRatio, 0, 1);

    return {
      candidate,
      score,
      centerScore,
      mainVisibleRatio,
      visibleHeight,
      centerDistance,
    };
  }

  function pickCenteredPost(candidates, viewportHeight, overrides) {
    const options = Object.assign({}, DEFAULT_OPTIONS, overrides || {});
    const scored = [];

    for (const candidate of candidates || []) {
      const result = scoreCandidate(candidate, viewportHeight, options);
      if (result) scored.push(result);
    }

    scored.sort((a, b) => b.score - a.score);
    if (scored.length === 0) return null;

    if (scored.length > 1 && scored[0].score - scored[1].score < options.ambiguityMargin) {
      return null;
    }

    return scored[0];
  }

  const api = {
    DEFAULT_OPTIONS,
    clamp,
    scoreCandidate,
    pickCenteredPost,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  root.DopaMaxxLockedOutSelector = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
