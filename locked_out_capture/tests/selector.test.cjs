const assert = require("node:assert/strict");
const selector = require("../../extension/locked_out_capture/selector.js");

function candidate(id, top, bottom) {
  return {
    id,
    rect: {
      top,
      bottom,
      height: bottom - top,
    },
  };
}

function testCenteredPostWins() {
  const result = selector.pickCenteredPost([
    candidate("top-half", -200, 300),
    candidate("centered", 220, 620),
    candidate("bottom-half", 650, 1050),
  ], 800);

  assert.equal(result.candidate.id, "centered");
  assert.ok(result.mainVisibleRatio >= 0.65);
}

function testHalfVisiblePostIsIgnored() {
  const result = selector.pickCenteredPost([
    candidate("barely-visible", -300, 100),
    candidate("centered", 250, 550),
  ], 800);

  assert.equal(result.candidate.id, "centered");
}

function testOutsideCenterBandIsIgnored() {
  const result = selector.pickCenteredPost([
    candidate("fully-visible-top", 0, 160),
    candidate("fully-visible-bottom", 640, 800),
  ], 800);

  assert.equal(result, null);
}

function testAmbiguousTieReturnsNull() {
  const result = selector.pickCenteredPost([
    candidate("near-center-a", 210, 390),
    candidate("near-center-b", 410, 590),
  ], 800);

  assert.equal(result, null);
}

function testTallDominantPostCanWin() {
  const result = selector.pickCenteredPost([
    candidate("very-long-post", -500, 1100),
    candidate("small-top", 20, 120),
  ], 800);

  assert.equal(result.candidate.id, "very-long-post");
  assert.equal(result.eligibility, "tall_dominant");
  assert.ok(result.viewportCoverage >= 0.55);
}

function testSmallCenteredPostCanWin() {
  const result = selector.pickCenteredPost([
    candidate("small-off-center", 80, 170),
    candidate("small-near-middle", 360, 450),
    candidate("small-low", 660, 750),
  ], 800);

  assert.equal(result.candidate.id, "small-near-middle");
  assert.equal(result.eligibility, "small_centered");
}

testCenteredPostWins();
testHalfVisiblePostIsIgnored();
testOutsideCenterBandIsIgnored();
testAmbiguousTieReturnsNull();
testTallDominantPostCanWin();
testSmallCenteredPostCanWin();

console.log("selector tests passed");
