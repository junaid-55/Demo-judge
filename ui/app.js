const AGENT_URL = "http://127.0.0.1:37123";
const BACKEND_URL = "http://127.0.0.1:38123";
const LANGUAGE_LABELS = { python: "Python", c: "C", cpp: "C++", javascript: "JavaScript", java: "Java", sql: "SQL" };
const STARTERS = {
  python: "import sys\n\n\ndef solve():\n    # Write your solution here.\n    pass\n\n\nif __name__ == '__main__':\n    solve()\n",
  c: "#include <stdio.h>\n\nint main(void) {\n    // Write your solution here.\n    return 0;\n}\n",
  cpp: "#include <iostream>\n\nint main() {\n    // Write your solution here.\n    return 0;\n}\n",
  javascript: "const fs = require('fs');\nconst input = fs.readFileSync(0, 'utf8');\n\n// Write your solution here.\n",
  java: "public class solution {\n    public static void main(String[] args) throws Exception {\n        // Write your solution here.\n    }\n}\n",
  sql: "-- Write one SELECT query here.\n",
};

const state = { problems: [], selected: null, runId: null, result: null, failure: null, activeTestId: null, retryTimer: null, connecting: false, theme: localStorage.getItem("chakrikoi-theme") || "latte" };
const elements = {
  status: document.querySelector("#connection-status"), sidebar: document.querySelector("#problem-sidebar"), scrim: document.querySelector("#sidebar-scrim"),
  sidebarToggle: document.querySelector("#sidebar-toggle"), sidebarClose: document.querySelector("#sidebar-close"), list: document.querySelector("#problem-list"),
  reconnect: document.querySelector("#reconnect-button"), themeToggle: document.querySelector("#theme-toggle"),
  content: document.querySelector("#problem-content"), editorProblem: document.querySelector("#editor-problem"), language: document.querySelector("#language"),
  source: document.querySelector("#source-code"), lines: document.querySelector("#line-numbers"), submit: document.querySelector("#submit-button"),
  resultsButton: document.querySelector("#results-button"), resultsDrawer: document.querySelector("#results-drawer"), resultsContent: document.querySelector("#results-content"), resultsClose: document.querySelector("#results-close"),
};

function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
function statusLabel(status) { return status.replaceAll("_", " "); }
function updateLines() { elements.lines.textContent = Array.from({ length: elements.source.value.split("\n").length }, (_, index) => index + 1).join("\n"); }
function setConnection(kind) { elements.status.className = `status-dot ${kind}`; elements.status.setAttribute("aria-label", `${kind} local agent`); }
function setSidebar(open) { elements.sidebar.classList.toggle("is-open", open); elements.sidebar.setAttribute("aria-hidden", String(!open)); elements.scrim.hidden = !open; }
function setResults(open) { elements.resultsDrawer.classList.toggle("is-open", open); elements.resultsDrawer.setAttribute("aria-hidden", String(!open)); if (open) renderResults(); }
function applyTheme() {
  document.body.dataset.theme = state.theme;
  const next = state.theme === "latte" ? "Macchiato" : "Latte";
  elements.themeToggle.setAttribute("aria-label", `Switch to ${next} theme`);
  elements.themeToggle.title = `Switch to ${next} theme`;
}

async function request(path, options = {}) {
  const response = await fetch(`${AGENT_URL}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Local agent returned HTTP ${response.status}`);
  return body;
}

async function backendRequest(path) {
  const response = await fetch(`${BACKEND_URL}${path}`, { headers: { "Content-Type": "application/json" } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Problem server returned HTTP ${response.status}`);
  return body;
}

function updateResultsButton(kind = "neutral") {
  elements.resultsButton.className = `results-button ${kind}`;
  elements.resultsButton.disabled = !state.result && !state.failure && !state.runId;
}

function renderProblems() {
  if (!state.problems.length) return;
  elements.list.innerHTML = state.problems.map(problem => `<button class="problem-button ${state.selected?.slug === problem.slug ? "selected" : ""}" data-slug="${escapeHtml(problem.slug)}"><strong>${escapeHtml(problem.title)}</strong><small>${escapeHtml(problem.slug)}</small></button>`).join("");
  elements.list.querySelectorAll("button").forEach(button => button.addEventListener("click", () => selectProblem(button.dataset.slug)));
}

function renderProblem(problem) {
  const samples = problem.tests.filter(test => test.is_sample).map((test, index) => `<article class="sample"><label>Sample ${index + 1} input</label><pre>${escapeHtml(test.input)}</pre><label>Expected output</label><pre>${escapeHtml(test.expected_output || "")}</pre></article>`).join("");
  const schema = problem.sql_schema ? `<details class="schema-accordion"><summary>Schema</summary><pre>${escapeHtml(problem.sql_schema)}</pre></details>` : "";
  elements.content.className = "";
  elements.content.innerHTML = `<p class="eyebrow">${escapeHtml(problem.slug)}</p><h2 id="problem-title">${escapeHtml(problem.title)}</h2><p>${escapeHtml(problem.statement)}</p><div class="limits"><span class="limit">${problem.time_limit_ms} ms</span><span class="limit">${problem.memory_limit_mb} MB</span></div>${schema}<div class="samples"><h3>Examples</h3>${samples || "<p class=\"muted\">No public examples.</p>"}</div>`;
}

async function selectProblem(slug) {
  try {
    const problem = await backendRequest(`/v1/problems/${encodeURIComponent(slug)}`);
    if (state.selected?.execution_mode === "sql" && state.selected.slug !== problem.slug) releaseSqlSession(state.selected.slug);
    state.selected = problem; state.result = null; state.failure = null; state.runId = null; state.activeTestId = null;
    renderProblems(); renderProblem(problem); setSidebar(false); updateResultsButton();
    elements.editorProblem.textContent = problem.title;
    elements.language.innerHTML = problem.allowed_languages.map(language => `<option value="${language}">${LANGUAGE_LABELS[language] || language}</option>`).join("");
    elements.language.disabled = false; elements.source.disabled = false; elements.submit.disabled = false;
    elements.source.value = STARTERS[elements.language.value] || ""; updateLines();
  } catch (error) { renderFailure(error.message); }
}

async function releaseSqlSession(slug) {
  try { await request(`/v1/sql-sessions/${encodeURIComponent(slug)}`, { method: "DELETE" }); } catch (_) { /* The agent may already be stopped. */ }
}

function renderFailure(message) {
  state.failure = message; state.result = null; updateResultsButton("failed");
  if (elements.resultsDrawer.classList.contains("is-open")) renderResults();
}

async function connect() {
  if (state.connecting) return;
  state.connecting = true; elements.reconnect.disabled = true; setConnection("waiting");
  try {
    const health = await request("/v1/health");
    if (!health.docker_available) throw new Error("Docker is not available to the local agent");
    setConnection("online");
  } catch (error) {
    setConnection("offline");
    clearTimeout(state.retryTimer); state.retryTimer = setTimeout(connect, 5000);
  } finally { state.connecting = false; elements.reconnect.disabled = false; }
}

async function loadProblems() {
  try {
    const catalog = await backendRequest("/v1/problems");
    state.problems = catalog.problems || [];
    if (!state.problems.length) throw new Error("The backend has no problems");
    renderProblems();
    await selectProblem(state.problems[0].slug);
  } catch (error) {
    elements.list.innerHTML = '<p class="muted">Problem server unavailable.</p>';
    elements.content.className = "empty-problem";
    elements.content.innerHTML = `<p class="eyebrow">Problem server</p><h2 id="problem-title">Problems unavailable</h2><p>${escapeHtml(error.message)}</p>`;
  }
}

function resultKind(result) {
  if (!result) return "neutral";
  return result.overall_status === "accepted" ? "accepted" : result.passed_test_cases ? "partial" : "failed";
}

function renderResults() {
  if (state.failure) {
    elements.resultsContent.innerHTML = `<div class="terminal-message error">${escapeHtml(state.failure)}</div>`;
    return;
  }
  if (!state.result) {
    elements.resultsContent.innerHTML = `<div class="terminal-message">${state.runId ? "The local agent is processing this submission." : "No submission result yet."}</div>`;
    return;
  }
  const passed = state.result.test_results.filter(test => test.status === "passed");
  const failed = state.result.test_results.filter(test => test.status !== "passed");
  const selected = state.result.test_results.find(test => test.test_case_id === state.activeTestId) || failed[0] || passed[0];
  state.activeTestId = selected?.test_case_id ?? null;
  const summary = test => {
    if (test.error_output) return `Error: ${test.error_output.replace(/\s+/g, " ").trim().slice(0, 46)}`;
    if (test.status === "passed") return `Output: ${(test.actual_output || "(empty)").replace(/\s+/g, " ").trim().slice(0, 45)}`;
    const expected = test.expected_output === undefined ? "unavailable" : (test.expected_output || "(empty)");
    const actual = test.actual_output || "(no output)";
    return `Expected ${expected}; got ${actual}`.replace(/\s+/g, " ").slice(0, 48);
  };
  const list = (tests, empty) => tests.length ? tests.map(test => `<button class="result-test ${state.activeTestId === test.test_case_id ? "selected" : ""}" data-test-id="${test.test_case_id}"><span><strong>Test ${test.test_case_id}</strong><small>${escapeHtml(summary(test))}</small></span><small>${test.runtime_ms} ms</small></button>`).join("") : `<p class="empty-list">${empty}</p>`;
  const detail = selected ? [
    `test ${selected.test_case_id} · ${statusLabel(selected.status)} · ${selected.runtime_ms} ms`,
    `\nexecution\nexit code: ${selected.exit_code === undefined || selected.exit_code === null ? "not available" : selected.exit_code}`,
    selected.input === undefined ? "" : `\ninput\n${selected.input || "(empty input)"}`,
    selected.expected_output === undefined ? "" : `\nexpected output\n${selected.expected_output || "(empty output)"}`,
    `\nactual output\n${selected.actual_output || "(no output)"}`,
    `\nstderr\n${selected.error_output || (selected.exit_code === 0 ? "(no traceback; process exited normally)" : "(no stderr captured)")}`,
  ].filter(Boolean).join("\n") : "No test selected.";
  elements.resultsContent.innerHTML = `<aside class="test-sidebar passed"><h2>Passed <span>${passed.length}</span></h2>${list(passed, "No passing tests")}</aside><aside class="test-sidebar failed"><h2>Failed <span>${failed.length}</span></h2>${list(failed, "No failed tests")}</aside><article class="terminal-output"><header><span class="prompt">judge@local</span><span> ${escapeHtml(state.result.overall_status)}</span></header><pre>${escapeHtml(detail)}</pre></article>`;
  elements.resultsContent.querySelectorAll("[data-test-id]").forEach(button => button.addEventListener("click", () => { state.activeTestId = Number(button.dataset.testId); renderResults(); }));
}

async function pollRun() {
  try {
    const current = await request(`/v1/runs/${encodeURIComponent(state.runId)}?wait=25`);
    if (current.status === "completed") {
      state.result = current.result; state.failure = null; state.activeTestId = null; state.runId = null;
      elements.submit.disabled = false; updateResultsButton(resultKind(state.result));
      if (elements.resultsDrawer.classList.contains("is-open")) renderResults();
      return;
    }
    if (current.status === "failed") { state.runId = null; elements.submit.disabled = false; renderFailure(current.detail); return; }
    if (elements.resultsDrawer.classList.contains("is-open")) renderResults();
    pollRun();
  } catch (error) { state.runId = null; elements.submit.disabled = false; renderFailure(error.message); }
}

async function submit() {
  if (!state.selected || !elements.source.value.trim()) return;
  elements.submit.disabled = true; state.result = null; state.failure = null; state.activeTestId = null; updateResultsButton("running");
  try {
    const run = await request("/v1/runs", { method: "POST", body: JSON.stringify({ problem_slug: state.selected.slug, language: elements.language.value, source_code: elements.source.value }) });
    state.runId = run.run_id; updateResultsButton("running"); pollRun();
  } catch (error) { elements.submit.disabled = false; state.runId = null; renderFailure(error.message); }
}

elements.sidebarToggle.addEventListener("click", () => setSidebar(true));
elements.sidebarClose.addEventListener("click", () => setSidebar(false));
elements.scrim.addEventListener("click", () => setSidebar(false));
elements.reconnect.addEventListener("click", () => connect());
elements.themeToggle.addEventListener("click", () => { state.theme = state.theme === "latte" ? "macchiato" : "latte"; localStorage.setItem("chakrikoi-theme", state.theme); applyTheme(); });
elements.resultsButton.addEventListener("click", () => setResults(!elements.resultsDrawer.classList.contains("is-open")));
elements.resultsClose.addEventListener("click", () => setResults(false));
elements.submit.addEventListener("click", submit);
elements.source.addEventListener("input", updateLines);
elements.source.addEventListener("keydown", event => {
  if (event.key === "Tab") { event.preventDefault(); const { selectionStart, selectionEnd, value } = elements.source; elements.source.value = `${value.slice(0, selectionStart)}  ${value.slice(selectionEnd)}`; elements.source.selectionStart = elements.source.selectionEnd = selectionStart + 2; updateLines(); }
});
elements.language.addEventListener("change", () => { elements.source.value = STARTERS[elements.language.value] || ""; updateLines(); });
window.addEventListener("pagehide", () => {
  if (state.selected?.execution_mode === "sql") fetch(`${AGENT_URL}/v1/sql-sessions/${encodeURIComponent(state.selected.slug)}`, { method: "DELETE", keepalive: true }).catch(() => {});
});
applyTheme();
loadProblems();
connect();
