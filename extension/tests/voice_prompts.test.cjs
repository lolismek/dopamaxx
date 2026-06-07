const assert = require("node:assert/strict");
const prompts = require("../voice_prompts.js");

assert.equal(prompts.PROMPT_BANK.length, 36);

const ids = new Set(prompts.PROMPT_BANK.map((prompt) => prompt.id));
assert.equal(ids.size, prompts.PROMPT_BANK.length);

for (const prompt of prompts.PROMPT_BANK) {
  assert.match(prompt.filename, /\.wav$/);
  assert.ok(prompt.text.length > 10);
  assert.ok(!prompt.text.includes("{site}"));
}

const blocked = prompts.createPrompt(
  prompts.EVENTS.BLOCKED_SITE_LOCKED_IN,
  {},
  () => 0
);

assert.equal(blocked.id, "blocked_001");
assert.equal(blocked.filename, "blocked_001_lock_the_fuck_in_gi.wav");
assert.equal(blocked.assetPath, "assets/voice_prompts/blocked_001_lock_the_fuck_in_gi.wav");
assert.equal(blocked.text, "Lock the fuck in, GI. That site can wait.");
assert.equal(blocked.rate, 0.86);
assert.equal(blocked.pitch, 0.78);

const breakPrompt = prompts.createPrompt(
  prompts.EVENTS.LOCKED_OUT_STARTED,
  {},
  () => 0
);

assert.equal(breakPrompt.id, "locked_out_001");
assert.equal(breakPrompt.text, "Good work. Take a break, GI.");
assert.equal(prompts.siteLabel("https://www.youtube.com/watch?v=abc"), "youtube.com");

console.log("voice prompt tests passed");
