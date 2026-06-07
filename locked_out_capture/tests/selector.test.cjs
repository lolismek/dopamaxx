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

testCenteredPostWins();
testHalfVisiblePostIsIgnored();
testOutsideCenterBandIsIgnored();
testAmbiguousTieReturnsNull();

console.log("selector tests passed");
