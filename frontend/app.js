const runBtn = document.getElementById("runBtn");
const queryInput = document.getElementById("query");
const offlineToggle = document.getElementById("offlineToggle");
const turnsRange = document.getElementById("turnsRange");
const turnsValue = document.getElementById("turnsValue");
const copyJsonBtn = document.getElementById("copyJsonBtn");
const runMessage = document.getElementById("runMessage");
const jsonPayload = document.getElementById("jsonPayload");
const connectionStatus = document.getElementById("connectionStatus");

const metricMode = document.getElementById("metricMode");
const metricProviders = document.getElementById("metricProviders");
const metricFlags = document.getElementById("metricFlags");
const metricTurns = document.getElementById("metricTurns");
const metricSummary = document.getElementById("metricSummary");
const flagBadge = document.getElementById("flagBadge");
const flagsList = document.getElementById("flagsList");
const thinkingList = document.getElementById("thinkingList");
const narrationList = document.getElementById("narrationList");
const toolCallList = document.getElementById("toolCallList");

let lastPayload = null;

document.querySelectorAll(".chip-btn").forEach((button) => {
  button.addEventListener("click", () => {
    const preset = button.getAttribute("data-query");
    if (preset) {
      queryInput.value = preset;
    }
  });
});

turnsRange.addEventListener("input", () => {
  turnsValue.textContent = String(turnsRange.value);
});

function setStatusText(message, isError = false) {
  runMessage.textContent = message;
  runMessage.style.color = isError ? "var(--bad)" : "var(--muted)";
}

function formatCode(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function setPlaceholder(list, text) {
  list.innerHTML = `<li class="placeholder">${text}</li>`;
}

function renderMetrics(payload) {
  const flags = Array.isArray(payload.flagged) ? payload.flagged.length : 0;
  metricMode.textContent = payload.mode || "offline";
  metricProviders.textContent = String(payload.provider_count ?? 0);
  metricFlags.textContent = String(flags);
  metricTurns.textContent = String(payload.turns ?? 0);
  metricSummary.textContent =
    payload.assistant_text || payload.narration || "Investigation completed with no assistant summary.";

  metricMode.textContent = payload.mode || "offline";
  flagBadge.textContent = `${flags} flagged`;
  flagBadge.className = "chip " + (flags > 0 ? "chip--warn" : "chip--neutral");

  if (payload.mode === "agent") {
    metricMode.textContent = "agent (live)";
    metricMode?.classList?.add?.("active");
  }
}

function renderTextList(container, payload, fallback) {
  if (!Array.isArray(payload) || payload.length === 0) {
    setPlaceholder(container, fallback);
    return;
  }

  container.innerHTML = "";
  payload.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = String(item || "");
    container.appendChild(li);
  });
}

function buildFlagCard(flag, index) {
  const card = document.createElement("article");
  card.className = "result-card";

  const provider = flag.provider || flag;
  const name = provider.name || provider.provider_name || provider.provider || `Flag ${index + 1}`;
  const addr = provider.address || provider.location || "Address not available";
  const maxLegal = flag.max_legal_capacity ?? flag.legal_max_capacity ?? "N/A";
  const licensed = flag.licensed_capacity ?? "N/A";
  const extras = {
    provider: name,
    address: addr,
    licensed_capacity: licensed,
    max_legal_capacity: maxLegal,
    excess_capacity: flag.excess_capacity ?? (Number.isFinite(Number(licensed)) && Number.isFinite(Number(maxLegal))
      ? Math.max(0, Number(licensed) - Number(maxLegal))
      : "N/A"),
    source: provider.source || "local",
    state: provider.state || "unknown",
  };

  card.innerHTML = `
    <h4>${index + 1}. ${escapeHtml(extras.provider)}</h4>
    <p class="result-meta">${escapeHtml(extras.address)} &nbsp;•&nbsp; ${escapeHtml(extras.state.toString())}</p>
    <details>
      <summary>Show full flag record</summary>
      <pre class="code-block">${escapeHtml(formatCode(flag))}</pre>
    </details>
  `;

  return card;
}

function renderFlags(flags) {
  if (!Array.isArray(flags) || flags.length === 0) {
    flagsList.innerHTML = `<p class="placeholder">No flags were raised for this run.</p>`;
    return;
  }

  flagsList.innerHTML = "";
  flags.forEach((flag, index) => {
    flagsList.appendChild(buildFlagCard(flag, index));
  });
}

function renderToolCalls(toolCalls) {
  if (!Array.isArray(toolCalls) || toolCalls.length === 0) {
    toolCallList.innerHTML = `<p class=\"placeholder\">No tool calls recorded for this run.</p>`;
    return;
  }
  toolCallList.innerHTML = "";
  toolCalls.forEach((entry) => {
    const card = document.createElement("article");
    card.className = "result-card";
    const status = entry.status || "ok";
    const statusClass = status === "ok" ? "chip--ok" : "chip--warn";
    const args = formatCode(entry.arguments || {});
    const result = formatCode(entry.result);
    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:0.6rem">
        <h4>${escapeHtml(entry.tool || "tool")}</h4>
        <span class="chip ${statusClass}">${escapeHtml(status)}</span>
      </div>
      <details>
        <summary>Input</summary>
        <pre class="code-block">${escapeHtml(args)}</pre>
      </details>
      <details>
        <summary>Result</summary>
        <pre class="code-block">${escapeHtml(result)}</pre>
      </details>
    `;
    toolCallList.appendChild(card);
  });
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderThinkingAndNarration(payload) {
  const thinking = Array.isArray(payload.thinking) ? payload.thinking : [];
  const narration = [];

  if (typeof payload.narration === "string") {
    narration.push(payload.narration);
  } else if (Array.isArray(payload.narration)) {
    narration.push(...payload.narration);
  } else if (typeof payload.assistant_text === "string") {
    narration.push(payload.assistant_text);
  }

  renderTextList(thinkingList, thinking, "No thinking trace available.");
  renderTextList(narrationList, narration, "No narration available.");
}

function renderPayload(payload) {
  jsonPayload.textContent = formatCode(payload);
  metricSummary.textContent =
    payload.assistant_text || (Array.isArray(payload.narration) ? payload.narration.join(" ") : "Investigation complete.");
  renderMetrics(payload);
  renderFlags(payload.flagged);
  renderThinkingAndNarration(payload);
  renderToolCalls(payload.tool_calls);
  copyJsonBtn.disabled = false;
}

async function checkConnection() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) {
      throw new Error("health check failed");
    }
    connectionStatus.textContent = "Backend: connected";
    connectionStatus.className = "chip chip--ok";
  } catch (error) {
    connectionStatus.textContent = "Backend: unavailable";
    connectionStatus.className = "chip chip--warn";
  }
}

runBtn.addEventListener("click", async () => {
  const query = queryInput.value.trim();
  if (!query) {
    setStatusText("Enter a query before running.", true);
    return;
  }
  runBtn.disabled = true;
  runBtn.textContent = "Running…";
  runMessage.textContent = "Starting investigation...";
  copyJsonBtn.disabled = true;

  try {
    const response = await fetch("/api/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        offline: offlineToggle.checked,
        max_turns: Number(turnsRange.value),
      }),
    });

    const payload = await response.json();
    lastPayload = payload;
    renderPayload(payload);
    runMessage.textContent = `Completed (${payload.status || "ok"})`;
  } catch (error) {
    runMessage.textContent = "Investigation failed. Check backend logs.";
    setStatusText("Investigation failed. Check network/backend.", true);
    jsonPayload.textContent = formatCode({
      error: String(error),
      status: "frontend_request_failed",
    });
    copyJsonBtn.disabled = false;
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "Run Investigation";
  }
});

copyJsonBtn.addEventListener("click", async () => {
  if (!lastPayload) return;
  const text = formatCode(lastPayload);
  await navigator.clipboard.writeText(text);
  setStatusText("JSON copied to clipboard.");
  setTimeout(() => setStatusText("Ready."), 1200);
});

turnsValue.textContent = turnsRange.value;
checkConnection();
