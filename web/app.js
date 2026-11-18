// The browser side of the game. It only draws what the server sends and
// passes the player's moves back. No rules or secrets live here.

const $ = (selector) => document.querySelector(selector);
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let gameId = null;
let caseId = "";             // which case to play; empty means the default
let state = null;
let current = null;          // id of the suspect being questioned
let tab = "interrogate";
let busy = false;            // true while a suspect is answering
let eventsSeen = 0;
let started = false;         // true once the player has left the briefing
let cases = [];              // the case cards shown on the case-files screen
const pick = { killer: null, motive: null, proof: [] };

// ---- talking to the server ---------------------------------------------
async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

async function streamReply(path, body, onText) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Something went wrong.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let full = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    full += decoder.decode(value, { stream: true });
    const cut = full.indexOf("[[ERROR]]");
    let text = cut >= 0 ? full.slice(0, cut) : full;
    // The server can replace a reply it has started sending (see guarded() in engine.py).
    const swap = text.lastIndexOf("[[REPLACE]]");
    if (swap >= 0) text = text.slice(swap + 11);
    onText(text);
  }
  const cut = full.indexOf("[[ERROR]]");
  if (cut >= 0) throw new Error(full.slice(cut + 9).trim());
}

// ---- small helpers ------------------------------------------------------
function toast(text, bad) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = text;
  const box = $("#toasts");
  box.appendChild(el);
  while (box.children.length > 3) box.firstElementChild.remove();
  setTimeout(() => el.remove(), 3500);
}

function showScreen(name) {
  for (const id of ["home", "cases", "briefing", "game", "accuse", "verdict"]) $("#screen-" + id).hidden = id !== name;
}

const suspect = (id) => state.suspects.find((s) => s.id === id);
const found = () => state.evidence.filter((e) => e.found);
const canAct = () => !busy && state.actions_left > 0 && !state.result;

function setState(next) {
  state = next;
  for (const line of state.events.slice(eventsSeen)) toast(line);
  eventsSeen = state.events.length;
  render();
}

// ---- drawing ------------------------------------------------------------
function render() {
  if (state.result) return renderVerdict();
  renderTop();
  renderSuspects();
  renderChat();
  renderPanel();
  renderBoard();
}

function renderTop() {
  const count = $("#actions");
  count.textContent = `${state.actions_left} / ${state.action_limit}`;
  count.classList.toggle("low", state.actions_left <= 3);
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === tab));
  $("#view-interrogate").hidden = tab !== "interrogate";
  $("#view-evidence").hidden = tab !== "evidence";
}

function segments(s) {
  const lit = Math.round((s.pressure / s.max_pressure) * 5);
  let html = "";
  for (let i = 1; i <= 5; i++) html += `<i class="${i <= lit ? (i >= 3 ? "hot" : "on") : ""}"></i>`;
  return `<div class="segs" title="Pressure: ${esc(s.mood)}">${html}</div>`;
}

function suspectCard(s, selected, withMeter) {
  return `<button class="suspect ${selected ? "on" : ""}" data-id="${s.id}">
    <span class="avatar">${esc(s.initials)}</span>
    <span><div class="name">${esc(s.name)}</div><div class="role">${esc(s.role)}</div>${withMeter ? segments(s) : ""}</span>
  </button>`;
}

function renderSuspects() {
  $("#suspect-list").innerHTML = state.suspects.map((s) => suspectCard(s, s.id === current, true)).join("");
}

function renderChat() {
  const s = suspect(current);
  $("#chat-name").textContent = s.name;
  $("#chat-about").textContent = s.about;
  const mood = $("#chat-mood");
  mood.textContent = s.mood;
  mood.classList.toggle("hot", s.pressure > 0);

  const box = $("#messages");
  if (!s.turns.length) {
    box.innerHTML = `<div class="empty">You have not asked ${esc(s.name.split(" ")[0])} anything yet.</div>`;
  } else {
    box.innerHTML = s.turns.map((t) =>
      (t.kind === "question"
        ? `<div class="bubble you"><div class="who">You</div><p>${esc(t.said)}</p></div>`
        : `<div class="event">You presented <b>${esc(t.evidence)}</b></div>`) +
      `<div class="bubble"><div class="who">${esc(s.name)}</div><p>${esc(t.answer)}</p></div>`
    ).join("");
  }
  box.scrollTop = box.scrollHeight;

  const input = $("#question");
  input.placeholder = state.actions_left > 0 ? `Ask ${s.name.split(" ")[0]} a question...` : "You are out of actions. Make your accusation.";
  input.disabled = !canAct();
  $("#ask").disabled = !canAct();
  $("#present").disabled = !canAct();
}

function renderPanel() {
  const have = found();
  $("#ev-count").textContent = `${have.length} of ${state.evidence.length}`;
  $("#ev-list").innerHTML =
    have.map((e) => `<div class="ev-row">${esc(e.name)}</div>`).join("") +
    state.evidence.filter((e) => !e.found).map(() => `<div class="ev-row no">Undiscovered</div>`).join("");
  $("#event-list").innerHTML = state.events.length
    ? state.events.slice().reverse().map((line) => `<div>${esc(line)}</div>`).join("")
    : `<div class="none">Nothing yet. Search the hotel from the Evidence tab.</div>`;
}

function renderBoard() {
  $("#board-n").textContent = found().length;
  $("#board-of").textContent = `of ${state.evidence.length} found`;
  $("#board-grid").innerHTML = state.evidence.map((e) => {
    if (e.found) {
      return `<div class="card"><div class="type red">${esc(e.tag)}</div><h3>${esc(e.name)}</h3><p>${esc(e.description)}</p><div class="rule"></div><div class="type where">Found in: ${esc(e.place)}</div></div>`;
    }
    if (e.unlocked) {
      return `<div class="locked open"><div class="type">${esc(e.tag)}</div><div class="place">${esc(e.place)}</div><button class="btn ghost" data-search="${e.id}" ${canAct() ? "" : "disabled"}>Search here</button></div>`;
    }
    return `<div class="locked"><div class="q">?</div><div class="type">${esc(e.tag)}</div><div class="hint">No reason to search here yet. A suspect may give you one.</div></div>`;
  }).join("");
}

function renderPresentMenu() {
  const s = suspect(current);
  const have = found();
  $("#present-menu").innerHTML = have.length
    ? have.map((e) => {
        const used = s.shown.includes(e.id);
        return `<button data-show="${e.id}" ${used ? "disabled" : ""}>${esc(e.name)}${used ? " (already shown)" : ""}</button>`;
      }).join("")
    : `<div class="none">You have no evidence yet. Search the hotel from the Evidence tab.</div>`;
}

// ---- moves --------------------------------------------------------------
async function talk(path, body, youHtml) {
  if (!canAct()) return;
  busy = true;
  const s = suspect(current);
  const box = $("#messages");
  box.querySelector(".empty")?.remove();
  box.insertAdjacentHTML("beforeend", youHtml + `<div class="bubble typing"><div class="who">${esc(s.name)}</div><p></p></div>`);
  const target = box.lastElementChild.querySelector("p");
  box.scrollTop = box.scrollHeight;
  $("#question").disabled = $("#ask").disabled = $("#present").disabled = true;
  try {
    await streamReply(path, body, (text) => { target.textContent = text; box.scrollTop = box.scrollHeight; });
  } catch (error) {
    toast(error.message, true);
  }
  busy = false;
  try { setState(await api(`/api/state?game=${gameId}`)); } catch (error) { toast(error.message, true); }
  $("#question").focus();
}

function ask() {
  const input = $("#question");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  talk("/api/ask", { game: gameId, suspect: current, text }, `<div class="bubble you"><div class="who">You</div><p>${esc(text)}</p></div>`);
}

function present(evidenceId) {
  const e = state.evidence.find((x) => x.id === evidenceId);
  $("#present-menu").hidden = true;
  talk("/api/show", { game: gameId, suspect: current, evidence: evidenceId }, `<div class="event">You presented <b>${esc(e.name)}</b></div>`);
}

async function search(evidenceId) {
  if (!canAct()) return;
  try { setState(await api("/api/search", { game: gameId, evidence: evidenceId })); } catch (error) { toast(error.message, true); }
}

// ---- accusation ---------------------------------------------------------
function renderAccuse() {
  $("#acc-killers").innerHTML = state.suspects.map((s) => suspectCard(s, s.id === pick.killer, false)).join("");
  $("#acc-motives").innerHTML = state.motives.map((m) =>
    `<button class="option ${m.id === pick.motive ? "on" : ""}" data-motive="${m.id}"><span class="mark"></span>${esc(m.text)}</button>`).join("");
  const have = found();
  $("#acc-proof").innerHTML = have.map((e) =>
    `<button class="option sq ${pick.proof.includes(e.id) ? "on" : ""}" data-proof="${e.id}"><span class="mark"></span>${esc(e.name)}</button>`).join("");
  const missing = state.evidence.length - have.length;
  $("#acc-hint").textContent = (have.length ? "Choose up to two. " : "You have found no evidence. ") +
    (missing ? `${missing} exhibit${missing === 1 ? " is" : "s are"} still undiscovered.` : "");

  const killer = pick.killer && suspect(pick.killer);
  const motive = state.motives.find((m) => m.id === pick.motive);
  const proof = have.filter((e) => pick.proof.includes(e.id)).map((e) => e.name.toLowerCase());
  $("#acc-statement").textContent = killer
    ? `I accuse ${killer.name} of killing ${state.victim}` +
      (motive ? `. Motive: ${motive.text.charAt(0).toLowerCase() + motive.text.slice(1)}` : "") +
      (proof.length ? `. Proof: the ${proof.join(" and the ")}.` : ".")
    : "Choose who you think did it.";
  const go = $("#accuse-go");
  go.textContent = killer ? `Accuse ${killer.name}` : "Accuse";
  go.disabled = !(pick.killer && pick.motive);
}

function renderVerdict() {
  const r = state.result;
  const screen = $("#screen-verdict");
  screen.classList.remove("solved", "weak", "wrong");
  screen.classList.add(r.verdict);
  $("#v-label").textContent = r.verdict === "solved" ? "Verdict" : r.verdict === "weak" ? "Verdict: not proven" : "Verdict: wrong";
  $("#v-headline").textContent = r.headline;
  $("#v-summary").textContent =
    r.verdict === "solved" ? `You named ${r.killer}, the reason, and the proof, in ${r.actions_used} of ${state.action_limit} actions.`
    : r.verdict === "weak" ? `${r.killer} did it, but ${!r.right_motive ? "you had the wrong motive" : "you had no proof that ties them to the killing"}. A good lawyer gets them off.`
    : `You accused ${r.accused}, who is innocent. ${r.killer} leaves on the first train out.`;
  $("#v-killer").textContent = `${r.killer} killed ${state.victim}`;
  $("#v-motive").textContent = r.motive;
  $("#v-method").textContent = r.method;
  if (r.verdict === "solved") markSolved(state.case);
  showScreen("verdict");
}

// ---- starting up --------------------------------------------------------
async function newGame() {
  const data = await api("/api/new", { case: caseId });
  gameId = data.game;
  eventsSeen = 0;
  started = false;
  $("#b-begin").textContent = "Begin investigation";
  current = data.state.suspects[0].id;
  tab = "interrogate";
  pick.killer = pick.motive = null;
  pick.proof = [];
  state = data.state;
  document.title = state.title;
  $("#b-title").textContent = state.title;
  $("#b-tagline").textContent = state.tagline;
  $("#b-number").textContent = state.case_number ? `Case file No. ${state.case_number}` : "Case file";
  $("#top-title").textContent = state.title;
  $("#top-number").textContent = state.case_number ? `Case ${state.case_number}` : "";
  $("#acc-question").textContent = `Who killed ${state.victim}?`;
  $("#b-intro").textContent = state.intro;
  $("#b-facts").innerHTML = state.public_facts.slice(1, 6).map((f) => `<li><span>${esc(f)}</span></li>`).join("");
  $("#b-stats").innerHTML = [[state.suspects.length, "Suspects"], [state.evidence.length, "Exhibits"], [state.action_limit, "Actions"]]
    .map(([n, label]) => `<div class="stat"><b>${n}</b><span class="type muted">${label}</span></div>`).join("");
  loadNotes();
  render();
  showScreen("briefing");
}

async function checkOllama() {
  try {
    const h = await api("/api/health");
    const banner = $("#banner");
    if (!h.ollama) { banner.textContent = "Ollama is not running, so the suspects cannot answer. Start Ollama, then reload this page."; banner.hidden = false; }
    else if (!h.model) { banner.textContent = `Ollama is running but the model "${h.model_name}" is not installed. Run: ollama pull ${h.model_name}`; banner.hidden = false; }
  } catch (error) { /* the game still loads without this check */ }
}

const notesKey = () => "case-notes-" + (state ? state.case : "");

function loadNotes() {
  // Notes are kept per case, in this browser only.
  const notes = $("#notes");
  try { notes.value = localStorage.getItem(notesKey()) || ""; } catch (error) { notes.value = ""; }
  notes.oninput = () => { try { localStorage.setItem(notesKey(), notes.value); } catch (error) { /* ignore */ } };
}

// ---- wiring -------------------------------------------------------------
$("#b-begin").onclick = () => { started = true; showScreen("game"); $("#question").focus(); };
$("#open-briefing").onclick = () => { $("#b-begin").textContent = "Back to the investigation"; showScreen("briefing"); };
$("#b-how").onclick = () => { $("#b-howto").hidden = !$("#b-howto").hidden; };
$("#ask").onclick = ask;
$("#question").addEventListener("keydown", (event) => { if (event.key === "Enter") ask(); });
$("#present").onclick = () => { renderPresentMenu(); $("#present-menu").hidden = !$("#present-menu").hidden; };
$("#open-accuse").onclick = () => { renderAccuse(); showScreen("accuse"); };
$("#accuse-back").onclick = $("#accuse-keep").onclick = () => showScreen("game");
$("#v-again").onclick = () => newGame().catch((error) => toast(error.message, true));
$("#h-cases").onclick = $("#b-cases").onclick = $("#v-cases").onclick = () => { renderCases(); showScreen("cases"); };
$("#c-home").onclick = () => showScreen("home");
$("#accuse-go").onclick = async () => {
  try { setState(await api("/api/accuse", { game: gameId, suspect: pick.killer, motive: pick.motive, evidence: pick.proof })); }
  catch (error) { toast(error.message, true); }
};

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-tab],[data-search],[data-show],[data-motive],[data-proof],[data-case],.suspect");
  if (!event.target.closest(".present-wrap")) $("#present-menu").hidden = true;
  if (!el) return;
  if (el.dataset.case) { caseId = el.dataset.case; newGame().catch((error) => toast(error.message, true)); }
  else if (el.dataset.tab) { tab = el.dataset.tab; renderTop(); }
  else if (el.dataset.search) search(el.dataset.search);
  else if (el.dataset.show) present(el.dataset.show);
  else if (el.dataset.motive) { pick.motive = el.dataset.motive; renderAccuse(); }
  else if (el.dataset.proof) {
    const id = el.dataset.proof;
    if (pick.proof.includes(id)) pick.proof = pick.proof.filter((x) => x !== id);
    else if (pick.proof.length < 2) pick.proof.push(id);
    else toast("Choose up to two.", true);
    renderAccuse();
  }
  else if (el.classList.contains("suspect")) {
    if (el.closest("#acc-killers")) { pick.killer = el.dataset.id; renderAccuse(); }
    else if (!busy) { current = el.dataset.id; renderSuspects(); renderChat(); }
  }
});

// ---- the case-files screen ------------------------------------------------
// Which cases this player has solved is remembered in this browser only.
function solvedCases() {
  try { return JSON.parse(localStorage.getItem("solved-cases") || "[]"); } catch (error) { return []; }
}

function markSolved(id) {
  const solved = solvedCases();
  if (solved.includes(id)) return;
  try { localStorage.setItem("solved-cases", JSON.stringify([...solved, id])); } catch (error) { /* not kept, that is all */ }
}

function renderCases() {
  const solved = solvedCases();
  $("#c-solved").textContent = cases.filter((c) => solved.includes(c.id)).length;
  $("#c-of").textContent = `of ${cases.length} solved`;
  $("#case-grid").innerHTML = cases.map((c) => {
    const done = solved.includes(c.id);
    return `<button class="case-card ${done ? "solved" : ""}" data-case="${esc(c.id)}">
      <img src="img/${esc(c.id)}.svg" alt="" onerror="this.onerror=null;this.src='img/default.svg'">
      <div class="case-body">
        <div class="type amber">${c.case_number ? "Case " + esc(c.case_number) : "Case"}</div>
        <h3>${esc(c.title)}</h3>
        <p>${esc(c.tagline)}</p>
      </div>
      ${done ? '<span class="done">Solved</span>' : ""}
    </button>`;
  }).join("");
  $("#h-stats").innerHTML = [[cases.length, "Cases"], [4, "Suspects in each"], [solved.filter((id) => cases.some((c) => c.id === id)).length, "Solved"]]
    .map(([n, label]) => `<div class="stat"><b>${n}</b><span class="type muted">${label}</span></div>`).join("");
}

async function loadCases() {
  try { cases = await api("/api/cases"); } catch (error) { toast(error.message, true); }
  renderCases();
}

loadCases();
checkOllama();
showScreen("home");
