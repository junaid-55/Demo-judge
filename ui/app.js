const DEFAULT_AGENT = "http://127.0.0.1:37123";
const LANGUAGE_LABELS = { python: "Python", c: "C", cpp: "C++", javascript: "JavaScript", java: "Java" };
const STARTERS = {
  python: "import sys\n\n\ndef solve():\n    # Write your solution here.\n    pass\n\n\nif __name__ == '__main__':\n    solve()\n",
  c: "#include <stdio.h>\n\nint main(void) {\n    // Write your solution here.\n    return 0;\n}\n",
  cpp: "#include <iostream>\n\nint main() {\n    // Write your solution here.\n    return 0;\n}\n",
  javascript: "const fs = require('fs');\nconst input = fs.readFileSync(0, 'utf8');\n\n// Write your solution here.\n",
  java: "public class solution {\n    public static void main(String[] args) throws Exception {\n        // Write your solution here.\n    }\n}\n",
};

const state = { problems: [], selected: null, agent: localStorage.getItem("chakrikoi-agent-url") || DEFAULT_AGENT, runId: null };
const elements = {
  url: document.querySelector("#agent-url"), connect: document.querySelector("#connect-button"), status: document.querySelector("#connection-status"),
  list: document.querySelector("#problem-list"), content: document.querySelector("#problem-content"), editorProblem: document.querySelector("#editor-problem"),
  language: document.querySelector("#language"), source: document.querySelector("#source-code"), lines: document.querySelector("#line-numbers"), submit: document.querySelector("#submit-button"), result: document.querySelector("#result-panel"),
};

elements.url.value = state.agent;

function agentUrl() { return elements.url.value.trim().replace(/\/$/, ""); }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
function setConnection(kind, text) { elements.status.className = `connection ${kind}`; elements.status.textContent = text; }
function updateLines() { elements.lines.textContent = Array.from({ length: elements.source.value.split("\n").length }, (_, index) => index + 1).join("\n"); }
function renderResult(content) { elements.result.innerHTML = content; }

async function request(path, options = {}) {
  const response = await fetch(`${agentUrl()}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Local agent returned HTTP ${response.status}`);
  return body;
}

function renderProblems() {
  elements.list.innerHTML = state.problems.map(problem => `<button class="problem-button ${state.selected?.slug === problem.slug ? "selected" : ""}" data-slug="${escapeHtml(problem.slug)}"><strong>${escapeHtml(problem.title)}</strong><small>${escapeHtml(problem.slug)}</small></button>`).join("");
  elements.list.querySelectorAll("button").forEach(button => button.addEventListener("click", () => selectProblem(button.dataset.slug)));
}

function renderProblem(problem) {
  const samples = problem.tests.filter(test => test.is_sample).map((test, index) => `<article class="sample"><label>Sample ${index + 1} input</label><pre>${escapeHtml(test.input)}</pre><label>Expected output</label><pre>${escapeHtml(test.expected_output || "")}</pre></article>`).join("");
  elements.content.className = "";
  elements.content.innerHTML = `<p class="eyebrow">${escapeHtml(problem.slug)}</p><h2 id="problem-title">${escapeHtml(problem.title)}</h2><p>${escapeHtml(problem.statement)}</p><div class="limits"><span class="limit">${problem.time_limit_ms} ms</span><span class="limit">${problem.memory_limit_mb} MB</span></div><div class="samples"><h3>Examples</h3>${samples || "<p class=\"muted\">No public examples.</p>"}</div>`;
}

async function selectProblem(slug) {
  try {
    const problem = await request(`/v1/problems/${encodeURIComponent(slug)}`);
    state.selected = problem;
    renderProblems(); renderProblem(problem);
    elements.editorProblem.textContent = problem.title;
    elements.language.innerHTML = problem.allowed_languages.map(language => `<option value="${language}">${LANGUAGE_LABELS[language] || language}</option>`).join("");
    elements.language.disabled = false; elements.source.disabled = false; elements.submit.disabled = false;
    elements.source.value = STARTERS[elements.language.value] || "";
    updateLines(); renderResult('<p class="muted">Ready to submit. Private tests stay on the local agent.</p>');
  } catch (error) { renderResult(`<div class="error-box">${escapeHtml(error.message)}</div>`); }
}

async function connect() {
  state.agent = agentUrl(); localStorage.setItem("chakrikoi-agent-url", state.agent);
  setConnection("waiting", "Connecting"); elements.connect.disabled = true;
  try {
    const health = await request("/v1/health");
    if (!health.docker_available) throw new Error("Docker is not available to the local agent");
    setConnection("online", "Agent connected");
    const catalog = await request("/v1/problems");
    state.problems = catalog.problems || [];
    renderProblems();
    if (!state.problems.length) elements.list.innerHTML = '<p class="muted">The backend has no problems.</p>';
    else await selectProblem(state.problems[0].slug);
  } catch (error) {
    state.problems = []; state.selected = null; renderProblems();
    setConnection("offline", "Agent unavailable");
    elements.content.className = "empty-problem";
    elements.content.innerHTML = `<p class="eyebrow">Connection error</p><h2 id="problem-title">Local agent is unavailable</h2><p>Start the installed Chakrikoi runner, then reconnect. ${escapeHtml(error.message)}</p>`;
  } finally { elements.connect.disabled = false; }
}

function statusLabel(status) { return status.replaceAll("_", " "); }
function renderCompleted(result) {
  const tests = result.test_results.map(test => `<div class="test-result"><small>Test ${test.test_case_id} · ${test.runtime_ms} ms</small><strong class="test-status ${test.status}">${escapeHtml(statusLabel(test.status))}</strong></div>`).join("");
  const errors = result.test_results.filter(test => test.status !== "passed" && (test.error_output || test.actual_output)).map(test => `Test ${test.test_case_id}: ${test.error_output || `Output: ${test.actual_output}`}`).join("\n\n");
  renderResult(`<div class="result-summary"><h3>${result.passed_test_cases}/${result.total_test_cases} tests passed</h3><span class="verdict ${result.overall_status}">${escapeHtml(statusLabel(result.overall_status))}</span></div><div class="test-grid">${tests}</div>${errors ? `<pre class="error-box">${escapeHtml(errors)}</pre>` : ""}`);
}

async function pollRun() {
  const current = await request(`/v1/runs/${encodeURIComponent(state.runId)}?wait=25`);
  if (current.status === "completed") { renderCompleted(current.result); elements.submit.disabled = false; return; }
  if (current.status === "failed") { renderResult(`<div class="error-box">${escapeHtml(current.detail)}</div>`); elements.submit.disabled = false; return; }
  renderResult(`<p class="runner-progress">${escapeHtml(statusLabel(current.status))}…</p>`);
  pollRun();
}

async function submit() {
  if (!state.selected || !elements.source.value.trim()) return;
  elements.submit.disabled = true; renderResult('<p class="runner-progress">Queuing submission…</p>');
  try {
    const run = await request("/v1/runs", { method: "POST", body: JSON.stringify({ problem_slug: state.selected.slug, language: elements.language.value, source_code: elements.source.value }) });
    state.runId = run.run_id; pollRun();
  } catch (error) { renderResult(`<div class="error-box">${escapeHtml(error.message)}</div>`); elements.submit.disabled = false; }
}

elements.connect.addEventListener("click", connect);
elements.submit.addEventListener("click", submit);
elements.source.addEventListener("input", updateLines);
elements.source.addEventListener("keydown", event => {
  if (event.key === "Tab") { event.preventDefault(); const { selectionStart, selectionEnd, value } = elements.source; elements.source.value = `${value.slice(0, selectionStart)}  ${value.slice(selectionEnd)}`; elements.source.selectionStart = elements.source.selectionEnd = selectionStart + 2; updateLines(); }
});
elements.language.addEventListener("change", () => { elements.source.value = STARTERS[elements.language.value] || ""; updateLines(); });
connect();
