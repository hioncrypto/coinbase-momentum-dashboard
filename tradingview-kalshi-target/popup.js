function formatUsd(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function render(state) {
  const targetEl = document.getElementById("target");
  const metaEl = document.getElementById("meta");
  const errorEl = document.getElementById("error");
  const enabledEl = document.getElementById("enabled");

  enabledEl.checked = state?.enabled !== false;
  targetEl.textContent = formatUsd(state?.target);

  const bits = [];
  if (state?.windowLabel) bits.push(state.windowLabel);
  if (state?.ticker) bits.push(state.ticker);
  if (state?.fetchedAt) {
    bits.push(`fetched ${new Date(state.fetchedAt).toLocaleTimeString()}`);
  }
  metaEl.textContent = bits.join(" · ") || "Waiting for Kalshi…";

  if (state?.error) {
    errorEl.hidden = false;
    errorEl.textContent = state.error;
  } else {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }
}

async function load() {
  const state = await chrome.runtime.sendMessage({ type: "get-target" });
  render(state);
}

document.getElementById("refresh").addEventListener("click", async () => {
  const state = await chrome.runtime.sendMessage({ type: "refresh-target" });
  render(state);
});

document.getElementById("enabled").addEventListener("change", async (e) => {
  const state = await chrome.runtime.sendMessage({
    type: "set-enabled",
    enabled: e.target.checked,
  });
  render(state);
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.kalshiTarget) {
    render(changes.kalshiTarget.newValue);
  }
});

load();
