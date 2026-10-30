// Rep page: renders the card stream from /rep/stream (Server-Sent Events), newest first.
const list = document.getElementById("cards");
const status = document.getElementById("status");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;   // textContent: card text is never parsed as HTML
  return node;
}

function render(card) {
  const box = el("article", `card ${card.category || card.kind}`);
  if (card.kind === "objection") {
    box.append(el("h2", "", card.title), el("p", "quote", `"${card.quote}"`));
    const tips = el("ul");
    card.tips.forEach((t) => tips.append(el("li", "", t)));
    box.append(tips);
  } else if (card.kind === "insight") {
    box.append(el("h2", "", "Copilot"), el("p", "", card.text));
  } else if (card.kind === "final") {
    box.append(el("h2", "", "Call ended"), el("p", "", card.text));
  } else {
    return null;
  }
  const time = new Date(card.ts * 1000).toLocaleTimeString();
  box.append(el("div", "meta", `${time} · call ${String(card.call_id).slice(0, 8)}${card.source ? " · " + card.source : ""}`));
  return box;
}

const source = new EventSource("stream");
source.onopen = () => { status.textContent = "live"; status.className = "status live"; };
source.onerror = () => { status.textContent = "reconnecting"; status.className = "status"; };
source.onmessage = (msg) => {
  const node = render(JSON.parse(msg.data));
  if (!node) return;
  document.getElementById("empty")?.remove();
  list.prepend(node);
};
