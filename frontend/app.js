/* ==========================================================================
   DOM References
   ========================================================================== */

const runBtn = document.getElementById("runBtn");
const queryInput = document.getElementById("query");
const scopeState = document.getElementById("scopeState");
const scopeCounty = document.getElementById("scopeCounty");
const applyScopeBtn = document.getElementById("applyScopeBtn");
const scopeSummary = document.getElementById("scopeSummary");
const offlineToggle = document.getElementById("offlineToggle");
const modeHint = document.getElementById("modeHint");
const turnsRange = document.getElementById("turnsRange");
const turnsValue = document.getElementById("turnsValue");
const copyJsonBtn = document.getElementById("copyJsonBtn");
const runMessage = document.getElementById("runMessage");
const jsonPayload = document.getElementById("jsonPayload");
const connectionStatus = document.getElementById("connectionStatus");

const emptyState = document.getElementById("emptyState");
const loadingState = document.getElementById("loadingState");
const resultsContainer = document.getElementById("resultsContainer");

const metricMode = document.getElementById("metricMode");
const metricProviders = document.getElementById("metricProviders");
const metricTurns = document.getElementById("metricTurns");
const thinkingList = document.getElementById("thinkingList");
const thinkingBadge = document.getElementById("thinkingBadge");
const thinkingAnalysisList = document.getElementById("thinkingAnalysisList");
const thinkingAnalysisBadge = document.getElementById("thinkingAnalysisBadge");
const narrativeContent = document.getElementById("narrativeContent");
const narrativeWordCount = document.getElementById("narrativeWordCount");
const narrationList = document.getElementById("narrationList");
const narrationBadge = document.getElementById("narrationBadge");
const toolCallList = document.getElementById("toolCallList");
const toolCountBadge = document.getElementById("toolCountBadge");
const timelineList = document.getElementById("timelineList");

const historyList = document.getElementById("historyList");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");
const propertyCoverageValue = document.getElementById("propertyCoverageValue");
const providerCoverageValue = document.getElementById("providerCoverageValue");

const tabBtnReport = document.getElementById("tabBtnReport");
const tabBtnInvestigation = document.getElementById("tabBtnInvestigation");
const tabReport = document.getElementById("tabReport");
const tabInvestigation = document.getElementById("tabInvestigation");

let lastPayload = null;
let activeHistoryId = null;

/* ==========================================================================
   View State Management
   ========================================================================== */

function showEmpty() {
  emptyState.hidden = false;
  loadingState.hidden = true;
  resultsContainer.hidden = true;
}

function showLoading() {
  emptyState.hidden = true;
  loadingState.hidden = false;
  resultsContainer.hidden = true;
}

function showResults() {
  emptyState.hidden = true;
  loadingState.hidden = true;
  resultsContainer.hidden = false;
}

/* ==========================================================================
   Tab Switching
   ========================================================================== */

const TAB_PREFERENCE_KEY = "surelock_active_tab";

function switchTab(tabName) {
  const isReport = tabName === "report";
  tabReport.hidden = !isReport;
  tabInvestigation.hidden = isReport;

  tabBtnReport.classList.toggle("tab-btn--active", isReport);
  tabBtnInvestigation.classList.toggle("tab-btn--active", !isReport);
  tabBtnReport.setAttribute("aria-selected", String(isReport));
  tabBtnInvestigation.setAttribute("aria-selected", String(!isReport));

  localStorage.setItem(TAB_PREFERENCE_KEY, tabName);
}

tabBtnReport.addEventListener("click", () => switchTab("report"));
tabBtnInvestigation.addEventListener("click", () => switchTab("investigation"));

/* ==========================================================================
   Utilities
   ========================================================================== */

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatCode(value) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

/* ==========================================================================
   Markdown Renderer (lightweight GFM-to-HTML, XSS-safe)
   ========================================================================== */

function renderMarkdown(md) {
  if (!md || typeof md !== "string") return "";

  const lines = md.split("\n");
  const out = [];
  let inCodeBlock = false;
  let codeBlockContent = [];
  let inList = false;
  let listType = "";
  let inTable = false;
  let tableRows = [];

  function flushList() {
    if (inList) {
      out.push(listType === "ol" ? "</ol>" : "</ul>");
      inList = false;
    }
  }

  function flushTable() {
    if (!inTable || tableRows.length === 0) return;
    let html = "<table>";
    tableRows.forEach((row, i) => {
      const cells = row.split("|").filter((c, idx, arr) => idx > 0 && idx < arr.length);
      if (i === 1 && cells.every(c => /^[\s\-:]+$/.test(c))) return;
      const tag = i === 0 ? "th" : "td";
      html += "<tr>" + cells.map(c => `<${tag}>${inlineFormat(c.trim())}</${tag}>`).join("") + "</tr>";
    });
    html += "</table>";
    out.push(html);
    inTable = false;
    tableRows = [];
  }

  function inlineFormat(text) {
    let s = escapeHtml(text);
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");
    s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
    s = s.replace(/_(.+?)_/g, "<em>$1</em>");
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, linkText, href) {
      const safeHref = escapeHtml(href);
      if (!/^https?:\/\//i.test(href)) return linkText;
      return '<a href="' + safeHref + '" rel="noopener">' + linkText + "</a>";
    });
    return s;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (/^```/.test(line)) {
      if (inCodeBlock) {
        out.push("<pre><code>" + escapeHtml(codeBlockContent.join("\n")) + "</code></pre>");
        codeBlockContent = [];
        inCodeBlock = false;
      } else {
        flushList();
        flushTable();
        inCodeBlock = true;
      }
      continue;
    }
    if (inCodeBlock) {
      codeBlockContent.push(line);
      continue;
    }

    if (/^\|/.test(line) && line.includes("|")) {
      flushList();
      if (!inTable) inTable = true;
      tableRows.push(line);
      continue;
    } else if (inTable) {
      flushTable();
    }

    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushList();
      out.push("<hr>");
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      flushList();
      const level = headingMatch[1].length;
      out.push(`<h${level}>${inlineFormat(headingMatch[2])}</h${level}>`);
      continue;
    }

    if (/^>\s?/.test(line)) {
      flushList();
      out.push(`<blockquote>${inlineFormat(line.replace(/^>\s?/, ""))}</blockquote>`);
      continue;
    }

    const ulMatch = line.match(/^[-*+]\s+(.+)/);
    if (ulMatch) {
      if (!inList || listType !== "ul") {
        flushList();
        out.push("<ul>");
        inList = true;
        listType = "ul";
      }
      out.push(`<li>${inlineFormat(ulMatch[1])}</li>`);
      continue;
    }

    const olMatch = line.match(/^\d+\.\s+(.+)/);
    if (olMatch) {
      if (!inList || listType !== "ol") {
        flushList();
        out.push("<ol>");
        inList = true;
        listType = "ol";
      }
      out.push(`<li>${inlineFormat(olMatch[1])}</li>`);
      continue;
    }

    if (line.trim() === "") {
      flushList();
      continue;
    }

    flushList();
    out.push(`<p>${inlineFormat(line)}</p>`);
  }

  if (inCodeBlock) {
    out.push("<pre><code>" + escapeHtml(codeBlockContent.join("\n")) + "</code></pre>");
  }
  flushList();
  flushTable();

  return out.join("\n");
}

/* ==========================================================================
   Scope Builder & Controls
   ========================================================================== */

const STATE_LABELS = {
  IL: "Illinois",
  MN: "Minnesota",
};

const FALLBACK_COVERAGE = {
  provider_states: ["IL", "MN"],
  property_county_coverage: {
    IL: {
      state_name: "Illinois",
      counties: [
        "Champaign",
        "Cook",
        "DeKalb",
        "DuPage",
        "Kane",
        "Kankakee",
        "Kendall",
        "Lake",
        "McHenry",
        "McLean",
        "Peoria",
        "Sangamon",
        "Will",
        "Winnebago",
      ],
    },
    MN: {
      state_name: "Minnesota",
      counties: [
        "Anoka",
        "Carver",
        "Dakota",
        "Hennepin",
        "Olmsted",
        "Ramsey",
        "Scott",
        "Sherburne",
        "St. Louis",
        "Stearns",
        "Washington",
        "Wright",
      ],
    },
  },
};

let coverageData = FALLBACK_COVERAGE;

function getStateCoverage(stateCode) {
  return coverageData?.property_county_coverage?.[stateCode] || null;
}

function getStateName(stateCode) {
  const covered = getStateCoverage(stateCode);
  return covered?.state_name || STATE_LABELS[stateCode] || stateCode;
}

function buildScopeQuery(stateCode, countyValue) {
  const stateName = getStateName(stateCode);
  const counties = getStateCoverage(stateCode)?.counties || [];

  if (!counties.length) {
    return `Investigate ${stateName} childcare providers and produce a comprehensive anomaly report with flagged and cleared providers.`;
  }

  if (countyValue === "__ALL__") {
    return `Investigate ${stateName} childcare providers across all covered counties (${counties.join(", ")}). Use county property/GIS cross-reference where available, prioritize high-risk anomalies, and produce a comprehensive report with flagged and cleared providers.`;
  }

  return `Investigate ${stateName} childcare providers in ${countyValue} County. Use county property/GIS cross-reference where available, prioritize high-risk anomalies, and produce a comprehensive report with flagged and cleared providers.`;
}

function populateStateOptions() {
  if (!scopeState) return;

  const options = Object.keys(coverageData.property_county_coverage || {});
  const ordered = ["IL", "MN"].filter((code) => options.includes(code));
  options.forEach((code) => {
    if (!ordered.includes(code)) ordered.push(code);
  });

  scopeState.innerHTML = "";
  ordered.forEach((code) => {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = `${getStateName(code)} (${code})`;
    scopeState.appendChild(option);
  });
}

function populateCountyOptions(stateCode) {
  if (!scopeCounty) return;
  const counties = getStateCoverage(stateCode)?.counties || [];

  scopeCounty.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = "__ALL__";
  allOption.textContent = `All covered counties (${counties.length})`;
  scopeCounty.appendChild(allOption);

  counties.forEach((county) => {
    const option = document.createElement("option");
    option.value = county;
    option.textContent = `${county} County`;
    scopeCounty.appendChild(option);
  });
}

function updateScopeSummary() {
  if (!scopeSummary || !scopeState || !scopeCounty) return;

  const stateCode = scopeState.value;
  const countyValue = scopeCounty.value;
  const stateName = getStateName(stateCode);
  const countyCount = getStateCoverage(stateCode)?.counties?.length || 0;

  if (countyValue === "__ALL__") {
    scopeSummary.textContent = `Scope: ${stateName} statewide county sweep (${countyCount} counties).`;
    return;
  }
  scopeSummary.textContent = `Scope: ${countyValue} County, ${stateName}.`;
}

function updateCoverageNotes() {
  if (propertyCoverageValue) {
    const parts = [];
    ["IL", "MN"].forEach((stateCode) => {
      const counties = getStateCoverage(stateCode)?.counties || [];
      if (counties.length) {
        parts.push(`${stateCode}: ${counties.length} counties`);
      }
    });
    propertyCoverageValue.textContent = parts.length
      ? parts.join(" | ")
      : "County coverage unavailable";
  }

  if (providerCoverageValue) {
    const providerStates = Array.isArray(coverageData.provider_states)
      ? coverageData.provider_states
      : ["IL", "MN"];
    const names = providerStates.map((code) => getStateName(code));
    if (names.length === 2) {
      providerCoverageValue.textContent = `Statewide in ${names[0]} and ${names[1]}`;
    } else {
      providerCoverageValue.textContent = `Statewide in ${names.join(", ")}`;
    }
  }
}

function applyScopeToPrompt() {
  if (!scopeState || !scopeCounty || !queryInput) return;
  queryInput.value = buildScopeQuery(scopeState.value, scopeCounty.value);
}

function initScopeBuilder() {
  if (!scopeState || !scopeCounty) return;

  populateStateOptions();
  if (scopeState.options.length > 0) {
    scopeState.value = scopeState.value || scopeState.options[0].value;
  }
  populateCountyOptions(scopeState.value);
  scopeCounty.value = "__ALL__";
  updateScopeSummary();
  updateCoverageNotes();

  if (!queryInput.value.trim()) {
    applyScopeToPrompt();
  }
}

scopeState?.addEventListener("change", () => {
  populateCountyOptions(scopeState.value);
  scopeCounty.value = "__ALL__";
  updateScopeSummary();
  applyScopeToPrompt();
});

scopeCounty?.addEventListener("change", () => {
  updateScopeSummary();
  applyScopeToPrompt();
});

applyScopeBtn?.addEventListener("click", () => {
  applyScopeToPrompt();
  setStatusText("Prompt updated from selected scope.");
});

async function loadCoverage() {
  try {
    const response = await fetch("/api/coverage");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    const hasCoverage =
      payload &&
      payload.property_county_coverage &&
      payload.property_county_coverage.IL &&
      payload.property_county_coverage.MN;
    if (hasCoverage) {
      coverageData = payload;
    }
  } catch (error) {
    // Keep fallback coverage silently.
  } finally {
    initScopeBuilder();
  }
}

turnsRange.addEventListener("input", () => {
  turnsValue.textContent = String(turnsRange.value);
});

function setStatusText(message, isError = false) {
  runMessage.textContent = message;
  runMessage.style.color = isError ? "#ef4444" : "#94a3b8";
}

function findReportStartIndex(text) {
  const source = String(text || "");
  const patterns = [
    /^#\s+SURELOCK HOMES(?:\s+—\s+|\s+)?(?:FINAL\s+)?INVESTIGATION REPORT\b/im,
    /^#\s+INVESTIGATION REPORT\b/im,
    /^##\s*1\.\s*INVESTIGATION NARRATIVE\b/im,
    /^1\.\s*INVESTIGATION NARRATIVE\b/im,
  ];
  let first = null;
  patterns.forEach((pattern) => {
    const match = source.match(pattern);
    if (!match || typeof match.index !== "number") return;
    if (first === null || match.index < first) first = match.index;
  });
  return first;
}

function stripFindingsBlock(text) {
  const source = String(text || "");
  const start = source.indexOf("SURELOCK_FINDINGS_JSON_START");
  const end = source.indexOf("SURELOCK_FINDINGS_JSON_END");
  if (start < 0 || end < 0 || end <= start) return source;
  return (source.slice(0, start) + source.slice(end + "SURELOCK_FINDINGS_JSON_END".length)).trim();
}

function sanitizeReportText(text) {
  let source = String(text || "").trim();
  if (!source) return "";
  const startAt = findReportStartIndex(source);
  if (startAt !== null && startAt >= 0) {
    source = source.slice(startAt).trimStart();
  }
  source = source.replace(/^\s*SURELOCK_METRICS:\s*\{.*\}\s*$/gim, "").trim();
  source = stripFindingsBlock(source);
  return source.trim();
}

function looksLikeFinalReportText(text) {
  const source = String(text || "");
  if (!source.trim()) return false;
  return (
    /^#\s+SURELOCK HOMES(?:\s+—\s+|\s+)?(?:FINAL\s+)?INVESTIGATION REPORT\b/im.test(source) ||
    /^#\s+INVESTIGATION REPORT\b/im.test(source) ||
    /^##\s*1\.\s*INVESTIGATION NARRATIVE\b/im.test(source)
  );
}

/* ==========================================================================
   Render Functions
   ========================================================================== */

function renderMetrics(payload) {
  metricMode.textContent = payload.mode === "agent" ? "Agent (Live)" : (payload.mode || "Offline");
  metricProviders.textContent = String(payload.provider_count ?? 0);
  metricTurns.textContent = String(payload.turns ?? 0);
}

function renderNarrative(payload) {
  const reportText = sanitizeReportText(payload.report_text || "");
  if (!reportText) {
    narrativeContent.innerHTML = '<p class="placeholder">Final report not available for this run. See Investigation tab for turn-by-turn narration.</p>';
    narrativeWordCount.textContent = "";
    return;
  }

  narrativeContent.innerHTML = renderMarkdown(reportText);
  const wordCount = reportText.split(/\s+/).filter(Boolean).length;
  narrativeWordCount.textContent = `${wordCount} words`;
}

function renderInvestigationNarration(payload) {
  const rawTurns = Array.isArray(payload.raw_turns) ? payload.raw_turns : [];
  const reportText = sanitizeReportText(payload.report_text || "");

  // Collect per-turn narration (exclude the final report turn which has no tool_results)
  const turns = [];
  rawTurns.forEach((turn) => {
    const text = (turn.assistant || "").trim();
    if (!text) return;
    if (reportText && text === reportText) return;
    if (looksLikeFinalReportText(text)) return;
    const tools = Array.isArray(turn.tool_results)
      ? turn.tool_results.map(tr => tr.tool).join(", ")
      : Array.isArray(turn.tools)
        ? turn.tools.map(t => t.tool || t).join(", ")
        : "";
    turns.push({ turn: turn.turn, text, tools });
  });

  const count = turns.length;
  narrationBadge.textContent = `${count} turn${count !== 1 ? "s" : ""}`;
  narrationBadge.className = "badge " + (count > 0 ? "badge--blue" : "badge--neutral");

  if (count === 0) {
    narrationList.innerHTML = '<p class="placeholder">No investigation narration available.</p>';
    return;
  }

  narrationList.innerHTML = "";
  turns.forEach((item) => {
    const section = document.createElement("div");
    section.className = "narration-turn";
    const toolsSuffix = item.tools ? ` — ${item.tools}` : "";
    section.innerHTML =
      `<div class="narration-turn__header">Turn ${item.turn}${toolsSuffix}</div>` +
      `<div class="narration-turn__body prose">${renderMarkdown(item.text)}</div>`;
    narrationList.appendChild(section);
  });
}

function renderThinking(payload) {
  // Build thinking from raw_turns (per-turn assistant reasoning) when the
  // thinking array only contains tool markers (OpenRouter mode).  For
  // Anthropic mode the thinking array has actual extended-thinking content.
  const reportText = sanitizeReportText(payload.report_text || "");
  const rawThinking = Array.isArray(payload.thinking) ? payload.thinking : [];
  const hasRealThinking = rawThinking.length > 0 && rawThinking.some(t => !String(t).startsWith("tool:"));

  let items = [];
  if (hasRealThinking) {
    items = rawThinking.filter(t => !String(t).startsWith("tool:"));
  } else if (Array.isArray(payload.raw_turns)) {
    // Use per-turn assistant narration as the thinking trace
    payload.raw_turns.forEach((turn) => {
      const text = (turn.assistant || "").trim();
      if (!text) return;
      if (reportText && text === reportText) return;
      if (looksLikeFinalReportText(text)) return;
      const tools = Array.isArray(turn.tool_results)
        ? turn.tool_results.map(tr => tr.tool).join(", ")
        : Array.isArray(turn.tools)
          ? turn.tools.map(t => t.tool || t).join(", ")
          : "";
      items.push({ turn: turn.turn, text, tools });
    });
  }

  const count = items.length;
  thinkingBadge.textContent = `${count} step${count !== 1 ? "s" : ""}`;
  thinkingBadge.className = "badge " + (count > 0 ? "badge--green" : "badge--neutral");

  if (count === 0) {
    thinkingList.innerHTML = '<p class="placeholder">No thinking trace available.</p>';
    return;
  }

  thinkingList.innerHTML = "";
  items.forEach((item) => {
    if (typeof item === "string") {
      // Anthropic extended-thinking mode
      const div = document.createElement("div");
      div.className = "thinking-item";
      div.textContent = item;
      thinkingList.appendChild(div);
    } else {
      // Per-turn reasoning (OpenRouter mode)
      const details = document.createElement("details");
      details.className = "thinking-turn";
      const toolsSuffix = item.tools ? ` — ${item.tools}` : "";
      details.innerHTML =
        `<summary class="thinking-turn__header">Turn ${item.turn}${toolsSuffix}</summary>` +
        `<div class="thinking-turn__body">${renderMarkdown(item.text)}</div>`;
      thinkingList.appendChild(details);
    }
  });
}

function renderThinkingAnalysis(payload) {
  const analysis = payload && typeof payload.thinking_analysis === "object" ? payload.thinking_analysis : null;
  if (!analysis) {
    thinkingAnalysisBadge.textContent = "No analysis";
    thinkingAnalysisBadge.className = "badge badge--neutral";
    thinkingAnalysisList.innerHTML = '<p class="placeholder">No thinking analysis available.</p>';
    return;
  }

  const unsurfaced = Array.isArray(analysis.unsurfaced_leads) ? analysis.unsurfaced_leads : [];
  const dropped = Array.isArray(analysis.dropped_paths) ? analysis.dropped_paths : [];
  const notes = Array.isArray(analysis.notes) ? analysis.notes : [];
  const signals = Array.isArray(analysis.signals_considered) ? analysis.signals_considered : [];
  const coverage = analysis.coverage || {};
  const badgeCount = unsurfaced.length + dropped.length;

  thinkingAnalysisBadge.textContent = `${badgeCount} insight${badgeCount !== 1 ? "s" : ""}`;
  thinkingAnalysisBadge.className = "badge " + (badgeCount > 0 ? "badge--amber" : "badge--neutral");

  const signalText = signals.slice(0, 6).map((s) => `${s.signal} (${s.count})`).join(", ") || "No signal data.";
  const summary = analysis.summary || "No summary available.";
  const providerCount = coverage.provider_search_count ?? "N/A";
  const investigatedCount = coverage.investigated_address_count ?? "N/A";
  const remainingCount = coverage.uninvestigated_provider_estimate ?? "N/A";

  const unsurfacedHtml = unsurfaced.length
    ? `<ul>${unsurfaced.map((item) =>
      `<li><strong>${escapeHtml(item.subject || "Unknown subject")}</strong> via <code>${escapeHtml(item.tool || "tool")}</code></li>`
    ).join("")}</ul>`
    : "<p>No unsurfaced leads.</p>";

  const droppedHtml = dropped.length
    ? `<ul>${dropped.map((item) => {
      const missing = Array.isArray(item.missing_followups) ? item.missing_followups.join(", ") : "";
      return `<li><strong>${escapeHtml(item.subject || "Unknown subject")}</strong> missing follow-up: <code>${escapeHtml(missing)}</code></li>`;
    }).join("")}</ul>`
    : "<p>No dropped paths.</p>";

  const notesHtml = notes.length
    ? `<ul>${notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")}</ul>`
    : "<p>No additional notes.</p>";

  thinkingAnalysisList.innerHTML = `
    <div class="analysis-card">
      <p><strong>Summary:</strong> ${escapeHtml(summary)}</p>
      <p><strong>Coverage:</strong> investigated ${escapeHtml(investigatedCount)} of ${escapeHtml(providerCount)} address-level targets (est. remaining: ${escapeHtml(remainingCount)}).</p>
      <p><strong>Signals considered:</strong> ${escapeHtml(signalText)}</p>
    </div>
    <div class="analysis-card">
      <h4>Unsurfaced Leads</h4>
      ${unsurfacedHtml}
    </div>
    <div class="analysis-card">
      <h4>Dropped Paths</h4>
      ${droppedHtml}
    </div>
    <div class="analysis-card">
      <h4>Notes</h4>
      ${notesHtml}
    </div>
  `;
}

function renderToolCalls(toolCalls) {
  const count = Array.isArray(toolCalls) ? toolCalls.length : 0;
  toolCountBadge.textContent = String(count);
  toolCountBadge.className = "badge " + (count > 0 ? "badge--purple" : "badge--neutral");

  if (count === 0) {
    toolCallList.innerHTML = '<p class="placeholder">No tool calls recorded for this run.</p>';
    return;
  }

  toolCallList.innerHTML = "";
  toolCalls.forEach((entry, index) => {
    const wrapper = document.createElement("details");
    wrapper.className = "tool-card";
    if (index < 3) wrapper.open = true;

    const status = entry.status || "ok";
    const badgeClass = status === "ok" ? "badge--green" : "badge--amber";
    const args = formatCode(entry.arguments || entry.input || {});
    const result = formatCode(entry.result);

    wrapper.innerHTML = `
      <summary class="tool-card__header">
        <h4>${escapeHtml(entry.tool || "tool")}</h4>
        <span class="badge ${badgeClass}">${escapeHtml(status)}</span>
      </summary>
      <div class="tool-card__body">
        <details>
          <summary>Input</summary>
          <pre class="code-block">${escapeHtml(args)}</pre>
        </details>
        <details>
          <summary>Result</summary>
          <pre class="code-block">${escapeHtml(result)}</pre>
        </details>
      </div>
    `;
    toolCallList.appendChild(wrapper);
  });
}

function buildTimelineEvents(payload) {
  const events = [];
  events.push({
    kind: "query",
    label: "Query submitted",
    detail: payload.query || "Investigation query received.",
    tone: "neutral",
  });

  const rawTurns = Array.isArray(payload.raw_turns) ? payload.raw_turns : [];
  if (rawTurns.length > 0) {
    rawTurns.forEach((turn) => {
      const turnNo = turn.turn || 0;
      const assistantText = (turn.assistant || "").toString().trim();
      if (assistantText) {
        if (looksLikeFinalReportText(assistantText)) {
          // Final report belongs in the Report tab only.
          return;
        }
        events.push({
          kind: "assistant",
          label: `Turn ${turnNo} - Assistant`,
          detail: assistantText,
          tone: "ok",
        });
      }
      if (Array.isArray(turn.tool_results)) {
        turn.tool_results.forEach((toolItem) => {
          const toolLabel = toolItem.tool || "tool";
          const hasError = toolItem.status && toolItem.status !== "ok";
          events.push({
            kind: "tool",
            label: `Turn ${turnNo} - ${toolLabel}`,
            detail: toolItem.result ? "(result returned)" : "(no result)",
            tone: hasError ? "warn" : "ok",
          });
        });
      }
      // Offline mode: turn has .tools array and .provider
      if (Array.isArray(turn.tools)) {
        turn.tools.forEach((toolItem) => {
          const toolLabel = toolItem.tool || "tool";
          events.push({
            kind: "tool",
            label: `Turn ${turnNo} - ${toolLabel}`,
            detail: toolItem.result ? "(result returned)" : "(no result)",
            tone: "ok",
          });
        });
      }
      if (turn.provider || turn.provider_name) {
        const providerName = typeof turn.provider === "string"
          ? turn.provider
          : (turn.provider?.name || turn.provider_name || "Provider");
        events.push({
          kind: "provider",
          label: `Turn ${turnNo} - Target`,
          detail: providerName,
          tone: "neutral",
        });
      }
    });
    return events;
  }

  if (Array.isArray(payload.tool_calls) && payload.tool_calls.length > 0) {
    payload.tool_calls.forEach((tool) => {
      events.push({
        kind: "tool",
        label: tool.tool || "tool",
        detail: formatCode(tool.input || tool.arguments || {}),
        tone: tool.status === "ok" ? "ok" : "warn",
      });
    });
  }

  return events;
}

function renderTimeline(payload) {
  const events = buildTimelineEvents(payload);
  if (events.length === 0) {
    timelineList.innerHTML = '<p class="placeholder">No timeline events available.</p>';
    return;
  }

  timelineList.innerHTML = "";
  events.forEach((event) => {
    const row = document.createElement("article");
    row.className = "timeline-item";
    const dotClass = event.tone === "warn" ? "timeline-dot--warn" : event.tone === "ok" ? "timeline-dot--ok" : "";
    const detailHtml = renderMarkdown(event.detail || "No details.");

    row.innerHTML = `
      <div class="timeline-dot ${dotClass}"></div>
      <div class="timeline-card">
        <p class="timeline-step">${escapeHtml(event.label || "System event")}</p>
        <div class="timeline-meta"><div class="prose">${detailHtml}</div></div>
      </div>
    `;
    timelineList.appendChild(row);
  });
}

/* ==========================================================================
   Main Render
   ========================================================================== */

function renderPayload(payload) {
  jsonPayload.textContent = formatCode(payload);
  renderMetrics(payload);
  renderNarrative(payload);
  renderInvestigationNarration(payload);
  renderThinking(payload);
  renderThinkingAnalysis(payload);
  renderToolCalls(payload.tool_calls);
  renderTimeline(payload);
  copyJsonBtn.disabled = false;
  showResults();
}

/* ==========================================================================
   Connection Check
   ========================================================================== */

async function checkConnection() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error("health check failed");
    connectionStatus.textContent = "Connected";
    connectionStatus.className = "status-badge status-badge--ok";
  } catch (error) {
    connectionStatus.textContent = "Unavailable";
    connectionStatus.className = "status-badge status-badge--error";
  }
}

/* ==========================================================================
   Streaming Activity Log
   ========================================================================== */

const loadingStatus = document.getElementById("loadingStatus");
const progressFill = document.getElementById("progressFill");
const activityLog = document.getElementById("activityLog");

function addActivity(icon, text, className) {
  const li = document.createElement("li");
  li.innerHTML = `<span class="activity-log__icon">${icon}</span><span class="activity-log__text ${className || ""}">${escapeHtml(text)}</span>`;
  activityLog.appendChild(li);
  activityLog.scrollTop = activityLog.scrollHeight;
}

function setProgress(pct) {
  progressFill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
}

function resetStream() {
  activityLog.innerHTML = "";
  setProgress(0);
  loadingStatus.textContent = "Starting investigation\u2026";
}

/* ==========================================================================
   Investigation Runner (SSE Streaming)
   ========================================================================== */

runBtn.addEventListener("click", async () => {
  const query = queryInput.value.trim();
  if (!query) {
    setStatusText("Enter a query before running.", true);
    return;
  }

  const isOffline = offlineToggle.checked;
  const maxTurns = Number(turnsRange.value);

  runBtn.disabled = true;
  runBtn.textContent = "Running\u2026";
  copyJsonBtn.disabled = true;
  setStatusText("Starting investigation...");
  resetStream();
  showLoading();

  try {
    const response = await fetch("/api/investigate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        offline: isOffline,
        max_turns: maxTurns,
      }),
    });

    if (!response.ok) {
      const bodyText = await response.text();
      let errMsg = `HTTP ${response.status}`;
      try {
        const body = JSON.parse(bodyText);
        errMsg = body.detail || body.error || errMsg;
      } catch {
        if (bodyText) errMsg = bodyText;
      }
      throw new Error(errMsg);
    }

    let sawComplete = false;
    let streamError = null;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const line = part.replace(/^data: /, "").trim();
        if (!line) continue;

        let event;
        try { event = JSON.parse(line); } catch { continue; }

        switch (event.event) {
          case "start":
            loadingStatus.textContent = `Investigating ${event.state || "targeted"} ${event.zip || ""}`;
            addActivity("\u{1F50D}", `Query: ${event.query}`, "");
            addActivity("\u{1F4CD}", `Target: ${event.state || "all"} ${event.zip || "areas"} (${event.provider || "engine"})`, "activity-log__text--muted");
            if (event.provider === "openrouter") {
              setProgress(2);
            }
            break;

          case "turn_start":
            addActivity("\u{1F9E0}", `Model turn ${event.turn}/${event.max_turns}`, "");
            setProgress(2 + ((event.turn - 1) / event.max_turns) * 94);
            break;

          case "assistant_text":
            addActivity("\u{1F4DD}", `Thinking: ${event.text.slice(0, 140)}${event.text.length > 140 ? "..." : ""}`, "activity-log__text--muted");
            break;

          case "nudge":
            addActivity("\u21AA\uFE0F", event.message || "Continuing investigation...", "activity-log__text--muted");
            break;

          case "report_start":
            loadingStatus.textContent = "Compiling final report";
            addActivity("\u{1F4C4}", "Writing final report", "activity-log__text--muted");
            break;

          case "providers_loaded":
            addActivity("\u{1F4CB}", `${event.count} providers found`, "");
            setProgress(5);
            break;

          case "provider_start":
            loadingStatus.textContent = `Checking ${event.name} (${event.turn}/${event.total})`;
            addActivity("\u{1F3E2}", `[${event.turn}/${event.total}] ${event.name} - ${event.address}`, "");
            break;

          case "tool_call":
            addActivity("\u{1F50E}", `Calling ${event.tool} for turn ${event.turn}`, "activity-log__text--muted");
            break;

          case "tool_payload":
            addActivity(
              "\u{1F6E0}\u{FE0F}",
              `${event.tool} payload: ${event.result?.status || "ok"}${event.result?.error ? ` - ${event.result.error}` : ""}`,
              event.status === "error" ? "activity-log__flag" : "activity-log__text--muted"
            );
            break;

          case "tool_result":
            addActivity("\u2699\u{FE0F}", `  ${event.tool}${event.sqft !== undefined ? ` (${event.sqft} sqft)` : ""}${event.max_legal !== undefined ? ` (max: ${event.max_legal})` : ""}`, "activity-log__text--muted");
            break;

          case "tool_error":
            addActivity("\u26A0\u{FE0F}", `  ${event.tool} failed: ${event.error || "timeout"}`, "activity-log__flag");
            break;

          case "turn_done":
            addActivity("\u{2705}", `Turn ${event.turn} complete`, "activity-log__text--muted");
            break;

          case "provider_done": {
            const pct = 5 + (event.turn / event.total) * 90;
            setProgress(pct);
            addActivity("\u2705", "  Provider check completed", "activity-log__text--muted");
            break;
          }

          case "complete":
            sawComplete = true;
            setProgress(100);
            loadingStatus.textContent = "Investigation complete";
            addActivity("\u{1F3C1}", "Done - investigation complete", "");
            if (event.payload.status === "error") {
              streamError = event.payload.error || "Investigation completed with an error.";
              addActivity("\u26A0\uFE0F", `Error: ${streamError}`, "activity-log__flag");
              setStatusText(`Investigation failed: ${streamError}`, true);
            } else {
              setStatusText(`Completed (${event.payload.status || "ok"})`);
            }
            lastPayload = event.payload;
            addToHistory(query, event.payload);
            // Brief delay so user can see the completion log
            await new Promise(r => setTimeout(r, 600));
            renderPayload(event.payload);
            break;

          case "error":
            streamError = event.error || "Investigation stream error";
            addActivity("\u26A0\uFE0F", `Error: ${streamError}`, "activity-log__flag");
            throw new Error(streamError);
        }
      }
    }

    if (!sawComplete) {
      throw new Error("Investigation stream ended before completion.");
    }
  } catch (error) {
    showResults();
    const message = error instanceof Error ? error.message : String(error);
    const detail = message || "Check network/backend.";
    setStatusText(`Investigation failed. ${detail}`, true);
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

/* ==========================================================================
   Offline Mode Preference (localStorage)
   ========================================================================== */

const OFFLINE_PREFERENCE_KEY = "surelock_offline_mode";

function updateModeHint() {
  modeHint.textContent = offlineToggle.checked ? "Offline mode" : "Online mode";
  const toggleLabel = offlineToggle.closest("[role='switch']");
  if (toggleLabel) {
    toggleLabel.setAttribute("aria-checked", String(offlineToggle.checked));
  }
}

function restoreModePreference() {
  const saved = localStorage.getItem(OFFLINE_PREFERENCE_KEY);
  offlineToggle.checked = saved === null ? false : saved === "1";
  updateModeHint();
}

offlineToggle.addEventListener("change", () => {
  localStorage.setItem(OFFLINE_PREFERENCE_KEY, offlineToggle.checked ? "1" : "0");
  updateModeHint();
});

/* ==========================================================================
   Copy JSON
   ========================================================================== */

copyJsonBtn.addEventListener("click", async () => {
  if (!lastPayload) return;
  const text = formatCode(lastPayload);
  await navigator.clipboard.writeText(text);
  setStatusText("JSON copied to clipboard.");
  setTimeout(() => setStatusText("Ready."), 1200);
});

/* ==========================================================================
   Investigation History (localStorage)
   ========================================================================== */

const HISTORY_KEY = "surelock_history";
const HISTORY_MAX = 20;

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function _compactPayloadForStorage(payload) {
  const compact = Object.assign({}, payload);
  // Strip heavy tool call results — keep tool name/status/arguments only
  if (Array.isArray(compact.tool_calls)) {
    compact.tool_calls = compact.tool_calls.map(tc => ({
      tool: tc.tool,
      arguments: tc.arguments,
      status: tc.status,
    }));
  }
  // Strip verbose raw_turns results
  if (Array.isArray(compact.raw_turns)) {
    compact.raw_turns = compact.raw_turns.map(turn => ({
      turn: turn.turn,
      assistant: typeof turn.assistant === "string" ? turn.assistant : "",
      provider: turn.provider,
      tool_results: Array.isArray(turn.tool_results)
        ? turn.tool_results.map(tr => ({ tool: tr.tool, status: tr.status }))
        : undefined,
      tools: Array.isArray(turn.tools)
        ? turn.tools.map(t => ({ tool: t.tool }))
        : undefined,
    }));
  }
  return compact;
}

function saveHistory(entries) {
  const json = JSON.stringify(entries);
  try {
    localStorage.setItem(HISTORY_KEY, json);
  } catch (e) {
    // Quota exceeded — evict oldest entries and retry
    while (entries.length > 1) {
      entries.pop();
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
        return;
      } catch (_) { /* keep evicting */ }
    }
    // Last resort: clear and store only the newest entry
    try {
      localStorage.removeItem(HISTORY_KEY);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
    } catch (_) {
      // Storage completely full — silently give up on history persistence
      console.warn("localStorage quota exceeded; history not saved.");
    }
  }
}

function addToHistory(query, payload) {
  const entries = loadHistory();
  const providers = payload.provider_count ?? 0;
  const mode = payload.mode === "agent" ? "Online" : "Offline";

  const entry = {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    query,
    timestamp: Date.now(),
    providers,
    mode,
    payload: _compactPayloadForStorage(payload),
  };

  entries.unshift(entry);
  if (entries.length > HISTORY_MAX) entries.length = HISTORY_MAX;
  saveHistory(entries);
  activeHistoryId = entry.id;
  renderHistory();
}

function removeFromHistory(id) {
  const entries = loadHistory().filter(e => e.id !== id);
  saveHistory(entries);
  if (activeHistoryId === id) activeHistoryId = null;
  renderHistory();
}

function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
  activeHistoryId = null;
  renderHistory();
}

function formatHistoryTime(ts) {
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now - d;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString();
}

function renderHistory() {
  const entries = loadHistory();
  historyList.innerHTML = "";

  if (entries.length === 0) {
    historyList.innerHTML = '<li class="history-list__empty">No investigations yet.</li>';
    return;
  }

  entries.forEach(entry => {
    const li = document.createElement("li");
    li.className = "history-item" + (entry.id === activeHistoryId ? " history-item--active" : "");

    const metaParts = [entry.mode, `${entry.providers}p`].join(" &middot; ");

    li.innerHTML = `
      <span class="history-item__query" title="${escapeHtml(entry.query)}">${escapeHtml(entry.query)}</span>
      <button class="history-item__delete" title="Remove" data-history-delete="${escapeHtml(entry.id)}">&times;</button>
      <span class="history-item__meta">${metaParts}</span>
      <span class="history-item__time">${formatHistoryTime(entry.timestamp)}</span>
    `;

    li.addEventListener("click", (e) => {
      if (e.target.closest("[data-history-delete]")) return;
      activeHistoryId = entry.id;
      lastPayload = entry.payload;
      queryInput.value = entry.query;
      renderPayload(entry.payload);
      setStatusText("Loaded from history.");
      renderHistory();
    });

    const deleteBtn = li.querySelector("[data-history-delete]");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        removeFromHistory(entry.id);
      });
    }

    historyList.appendChild(li);
  });
}

clearHistoryBtn.addEventListener("click", () => {
  clearHistory();
});

/* ==========================================================================
   Init
   ========================================================================== */

restoreModePreference();
turnsValue.textContent = turnsRange.value;
checkConnection();
loadCoverage();
renderHistory();
showEmpty();

// Restore active tab preference
const savedTab = localStorage.getItem(TAB_PREFERENCE_KEY);
if (savedTab === "investigation") switchTab("investigation");
