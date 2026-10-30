// Rep page: renders the card stream from /rep/stream (Server-Sent Events), newest first.
const list = document.getElementById("cards");
const status = document.getElementById("status");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;   // textContent: card text is never parsed as HTML
  return node;
}

function fields(pairs) {
  const dl = el("dl");
  pairs.filter(([, v]) => v !== null && v !== undefined && v !== "")
       .forEach(([k, v]) => dl.append(el("dt", "", k), el("dd", "", String(v))));
  return dl;
}

function render(card) {
  let box;
  if (card.kind === "order") {
    box = el("article", "card order");
    box.append(el("h2", "", card.found ? `Order ${card.order_id}` : `Order ${card.order_id} not found`));
    if (card.found) {
      box.append(fields([["Customer", card.customer], ["Phone", card.phone], ["Status", card.status],
        ["Items", card.items.join(", ")], ["Total", card.total.toFixed(2)], ["ETA", card.eta], ["Notes", card.notes]]));
    }
  } else if (card.kind === "credit") {
    box = el("article", `card ${card.status}`);
    box.append(el("h2", "", `Credit ${card.status}: ${card.amount.toFixed(2)} ${card.currency} on ${card.order_id}`),
               el("p", "", card.detail));
    if (card.reason) box.append(el("p", "quote", card.reason));
  } else if (card.kind === "insight") {
    box = el("article", "card insight");
    box.append(el("h2", "", "Copilot"), el("p", "", card.text));
  } else if (card.kind === "final") {
    box = el("article", "card final");
    box.append(el("h2", "", "Call ended"), el("p", "", card.text));
  } else {
    return null;
  }
  const time = new Date(card.ts * 1000).toLocaleTimeString();
  box.append(el("div", "meta", `${time} · call ${String(card.call_id).slice(0, 8)}`));
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
