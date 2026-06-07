const feedEl = document.getElementById("feed");
const statusEl = document.getElementById("status");

loadFeed();

async function loadFeed() {
  const response = await sendMessage({ type: "get_microdose_feed" });
  if (!response.ok) {
    statusEl.textContent = "ERROR";
    renderEmpty(response.error || "feed unavailable");
    return;
  }

  const items = response.items || [];
  statusEl.textContent = `${items.length} READY`;
  renderFeed(items);
}

function renderFeed(items) {
  feedEl.innerHTML = "";
  if (!items.length) {
    renderEmpty("no ready posts");
    return;
  }

  for (const item of items) {
    const article = document.createElement("article");
    article.className = "post";

    const head = document.createElement("div");
    head.className = "post-head";
    head.innerHTML = `<span class="rank">#${item.rank}</span><span class="score">${scoreText(item.predicted_reward)}</span>`;

    const text = document.createElement("div");
    text.className = "post-text";
    text.textContent = item.text || "(no text)";

    const meta = document.createElement("div");
    meta.className = "post-meta";
    meta.appendChild(authorNode(item));
    meta.appendChild(linkNode(item));

    const rationale = document.createElement("div");
    rationale.className = "rationale";
    rationale.textContent = item.rationale || "";

    const actions = document.createElement("div");
    actions.className = "actions";
    actions.appendChild(statusButton(item.queue_id, "consumed", "Done", true));
    actions.appendChild(statusButton(item.queue_id, "dismissed", "Dismiss", false));

    article.appendChild(head);
    article.appendChild(text);
    article.appendChild(meta);
    article.appendChild(rationale);
    article.appendChild(actions);
    feedEl.appendChild(article);
  }
}

function renderEmpty(message) {
  feedEl.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = message;
  feedEl.appendChild(empty);
}

function authorNode(item) {
  const span = document.createElement("span");
  span.textContent = item.author ? `@${item.author}` : item.post_id;
  return span;
}

function linkNode(item) {
  if (!item.url) {
    const span = document.createElement("span");
    span.textContent = "queued";
    return span;
  }

  const link = document.createElement("a");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "open";
  return link;
}

function statusButton(queueId, status, label, primary) {
  const button = document.createElement("button");
  button.textContent = label;
  if (primary) button.className = "primary";
  button.addEventListener("click", async () => {
    button.disabled = true;
    const response = await sendMessage({
      type: "update_microdose_item",
      queueId,
      status,
    });
    if (!response.ok) {
      statusEl.textContent = "ERROR";
      button.disabled = false;
      return;
    }
    await loadFeed();
  });
  return button;
}

function scoreText(score) {
  if (!Number.isFinite(score)) return "score n/a";
  return `score ${score.toFixed(3)}`;
}

function sendMessage(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      resolve(response || { ok: false, error: "no response" });
    });
  });
}
