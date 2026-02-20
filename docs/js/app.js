/* ==========================================================================
   Surelock Homes — Static Report Site JS
   ========================================================================== */

/* --- Utilities --- */

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
   Copied from frontend/app.js
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
   Page Detection & Initialization
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page === "index") {
    initIndex();
  } else if (page === "report") {
    initReport();
  }
});

/* ==========================================================================
   Index Page
   ========================================================================== */

function initIndex() {
  const grid = document.getElementById("runsGrid");
  const loading = document.getElementById("loadingState");

  fetch("data/runs.json")
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(runs => {
      loading.hidden = true;

      if (!runs.length) {
        grid.innerHTML = '<p class="placeholder">No investigation runs found. Run <code>python scripts/build_pages.py</code> to generate data.</p>';
        return;
      }

      grid.innerHTML = "";
      runs.forEach(run => {
        const card = document.createElement("a");
        card.className = "run-card";
        card.href = `report.html?run=${encodeURIComponent(run.id)}`;

        const modeBadge = `<span class="case-badge case-badge--mode">${escapeHtml(run.mode === "agent" ? "Live" : "Offline")}</span>`;

        card.innerHTML = `
          <div class="run-card__body">
            <p class="run-card__query">${escapeHtml(run.query)}</p>
            <div class="run-card__meta">
              <span class="run-card__stat">${escapeHtml(run.timestamp)}</span>
              <span class="run-card__stat">${run.provider_count} providers</span>
              <span class="run-card__stat">${run.turns} turns</span>
            </div>
          </div>
          <div class="run-card__badge" style="display:flex;gap:0.35rem;flex-direction:column;align-items:flex-end">
            ${modeBadge}
          </div>
        `;
        grid.appendChild(card);
      });
    })
    .catch(err => {
      loading.hidden = true;
      grid.innerHTML = `<p class="placeholder">Failed to load runs: ${escapeHtml(err.message)}</p>`;
    });
}

/* ==========================================================================
   Report Page
   ========================================================================== */

function initReport() {
  const params = new URLSearchParams(window.location.search);
  const runId = params.get("run");

  const loading = document.getElementById("loadingState");
  const content = document.getElementById("reportContent");
  const errorEl = document.getElementById("errorState");

  if (!runId) {
    loading.hidden = true;
    errorEl.hidden = false;
    errorEl.textContent = "No run ID specified. Return to the index page.";
    return;
  }

  fetch(`data/runs/${encodeURIComponent(runId)}.json`)
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(data => {
      loading.hidden = true;
      content.hidden = false;
      renderReport(data);
    })
    .catch(err => {
      loading.hidden = true;
      errorEl.hidden = false;
      errorEl.textContent = `Failed to load run ${runId}: ${err.message}`;
    });
}

function renderReport(data) {
  // Query and timestamp
  document.getElementById("reportQuery").textContent = data.query || "Unknown query";
  document.getElementById("reportTimestamp").textContent = data.timestamp || data.id;

  // KPI strip
  document.getElementById("metricMode").textContent = data.mode === "agent" ? "Agent (Live)" : (data.mode || "Offline");
  document.getElementById("metricProviders").textContent = String(data.provider_count ?? 0);
  document.getElementById("metricTurns").textContent = String(data.turns ?? 0);

  // Report tab: render report_text as markdown
  const reportContent = document.getElementById("narrativeContent");
  const reportText = data.report_text || "";
  if (reportText.trim()) {
    reportContent.innerHTML = renderMarkdown(reportText);
    const wordCount = reportText.split(/\s+/).filter(Boolean).length;
    document.getElementById("narrativeWordCount").textContent = `${wordCount} words`;
  } else {
    reportContent.innerHTML = '<p class="placeholder">No report available.</p>';
  }

  // Investigation Log tab: render narration as markdown
  const narrationContent = document.getElementById("narrationContent");
  const narration = data.narration || "";
  if (narration.trim()) {
    narrationContent.innerHTML = renderMarkdown(narration);
    const wordCount = narration.split(/\s+/).filter(Boolean).length;
    document.getElementById("narrationWordCount").textContent = `${wordCount} words`;
  } else {
    narrationContent.innerHTML = '<p class="placeholder">No investigation log available.</p>';
  }

  // Tab switching
  initTabs();
}

function initTabs() {
  const tabBtnReport = document.getElementById("tabBtnReport");
  const tabBtnNarration = document.getElementById("tabBtnNarration");
  const tabReport = document.getElementById("tabReport");
  const tabNarration = document.getElementById("tabNarration");

  function switchTab(tabName) {
    const isReport = tabName === "report";
    tabReport.hidden = !isReport;
    tabNarration.hidden = isReport;
    tabBtnReport.classList.toggle("tab-btn--active", isReport);
    tabBtnNarration.classList.toggle("tab-btn--active", !isReport);
  }

  tabBtnReport.addEventListener("click", () => switchTab("report"));
  tabBtnNarration.addEventListener("click", () => switchTab("narration"));
}
