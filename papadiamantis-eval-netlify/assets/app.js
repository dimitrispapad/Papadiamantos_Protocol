const APP_VERSION = "0.2.0";
const NETLIFY_FORM_NAME = "papadiamantis-eval"; // MUST match index.html form name + hidden form-name value
const STORAGE_PREFIX = "pap_eval_v2";

function qs(name){ return new URL(window.location.href).searchParams.get(name); }
function $(id){ return document.getElementById(id); }
function clamp(n, lo, hi){ return Math.max(lo, Math.min(hi, n)); }
function nowISO(){ return new Date().toISOString(); }

async function loadJSON(path){
  const r = await fetch(path, { cache: "no-store" });
  if(!r.ok) throw new Error(`Failed to load ${path}: ${r.status}`);
  return await r.json();
}

function updateBadges(expertId, idx, total){
  $("expertBadge").textContent = `Expert: ${expertId || "—"}`;
  const pct = total ? Math.round((idx/total)*100) : 0;
  $("progressBadge").textContent = `${pct}%`;
}

function storageKey(expertId, assignmentId){
  return `${STORAGE_PREFIX}::${expertId}::${assignmentId}`;
}

function defaultState(){
  return {
    started:false,
    taskIndex:0,
    answers:{},
    startedAt:null,
    finishedAt:null,

    // anti-duplicate / idempotency
    clientSessionId:null,
    submitted:false,
    lastSubmissionUuid:null,

    // lightweight timing
    taskTimeMs:{},
    _lastTaskKey:null,
    _lastTaskEnterAt:null
  };
}

function saveState(key, state){ localStorage.setItem(key, JSON.stringify(state)); }
function loadState(key){
  const raw = localStorage.getItem(key);
  if(!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

function randomId(prefix=""){
  const buf = new Uint8Array(12);
  crypto.getRandomValues(buf);
  const s = Array.from(buf).map(b => b.toString(16).padStart(2,"0")).join("");
  return prefix ? `${prefix}_${s}` : s;
}

function getAnswerKey(task){
  return task.task_uid || task.task_id;
}

let assignment=null, expertId=null, stateKey=null, state=null;

function ensureClientSessionId(){
  const k = `${STORAGE_PREFIX}::client_session_id::${expertId || "unknown"}`;
  let v = localStorage.getItem(k);
  if(!v){
    v = randomId("sess");
    localStorage.setItem(k, v);
  }
  return v;
}

/**
 * Netlify Forms reliable submit:
 * - A real <form data-netlify="true"> exists in HTML at build time
 * - We fill its fields
 * - We submit it into a hidden iframe so user stays on page
 */
function submitViaNetlifyForm(data){
  const form = document.getElementById("netlifyForm");
  const iframe = document.querySelector('iframe[name="netlify_iframe"]');

  if(!form) throw new Error("netlifyForm not found in index.html");
  if(!iframe) throw new Error("netlify_iframe not found in index.html");

  for(const [k,v] of Object.entries(data)){
    const el = form.elements[k];
    if(el) el.value = String(v ?? "");
  }

  return new Promise((resolve) => {
    let doneCalled = false;
    const done = () => {
      if(doneCalled) return;
      doneCalled = true;
      iframe.removeEventListener("load", done);
      resolve();
    };

    iframe.addEventListener("load", done);
    form.submit();

    // fallback in case iframe load doesn't fire (rare)
    setTimeout(done, 2500);
  });
}

function renderAdminExpertLinks(){
  if (qs("admin") !== "1") return;

  const box = $("adminExpertPicker");
  const wrap = $("expertLinks");
  if (!box || !wrap) return;

  box.style.display = "block";
  wrap.innerHTML = "";

  const base = new URL(window.location.href);
  for (let i = 1; i <= 9; i++) {
    const ex = `E${i}`;
    const u = new URL(base);
    u.searchParams.set("expert", ex);
    u.searchParams.set("admin", "1");

    const a = document.createElement("a");
    a.className = "btn small";
    a.href = u.pathname + u.search;
    a.textContent = ex;
    wrap.appendChild(a);
  }
}

function renderScale(name, currentValue, onChange){
  const wrap = document.createElement("div");
  wrap.className = "scale";
  for(let i=1;i<=5;i++){
    const lab = document.createElement("label");
    const inp = document.createElement("input");
    inp.type = "radio";
    inp.name = name;
    inp.value = String(i);
    if(Number(currentValue) === i) inp.checked = true;
    inp.addEventListener("change", () => onChange(i));
    const span = document.createElement("span");
    span.textContent = String(i);
    lab.appendChild(inp); lab.appendChild(span);
    wrap.appendChild(lab);
  }
  return wrap;
}

function renderClusterTask(task, answer, onUpdate){
  const body = document.createElement("div");
  body.className = "grid";

  const intro = document.createElement("p");
  intro.className = "muted";
  intro.textContent = "Βαθμολογήστε τη συνάφεια κάθε έργου με την ομάδα (1–5) και δηλώστε «εκτός ομάδας» όπου χρειάζεται.";
  body.appendChild(intro);

  const a = answer || { items:{}, cluster_label:"", cluster_note:"" };
  const itemsWrap = document.createElement("div");
  itemsWrap.className = "grid";

  const taskKey = getAnswerKey(task);

  task.items.forEach((it) => {
    const itemKey = it.doc_id;
    const itemAns = a.items[itemKey] || {coherence:null, misplaced:false, note:""};

    const card = document.createElement("div");
    card.className = "item";

    const title = document.createElement("div");
    title.className = "item-title";
    const left = document.createElement("div");
    left.textContent = it.title || it.doc_id;
    const right = document.createElement("div");
    right.className = "pill";
    right.textContent = it.doc_id;
    title.appendChild(left); title.appendChild(right);
    card.appendChild(title);

    if(it.excerpt){
      const ex = document.createElement("p");
      ex.className = "muted";
      ex.textContent = it.excerpt;
      card.appendChild(ex);
    }

    card.appendChild(renderScale(`coh_${taskKey}_${itemKey}`, itemAns.coherence, (val)=>{
      itemAns.coherence = val;
      a.items[itemKey] = itemAns;
      onUpdate(a);
    }));

    const row = document.createElement("div");
    row.className = "row";

    const toggle = document.createElement("label");
    toggle.className = "toggle";
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = !!itemAns.misplaced;
    chk.addEventListener("change", ()=>{
      itemAns.misplaced = chk.checked;
      a.items[itemKey] = itemAns;
      onUpdate(a);
    });
    const tspan = document.createElement("span");
    tspan.textContent = "Εκτός ομάδας (misplaced)";
    toggle.appendChild(chk); toggle.appendChild(tspan);
    row.appendChild(toggle);

    const note = document.createElement("input");
    note.type = "text";
    note.placeholder = "Σύντομη σημείωση (προαιρετικό)";
    note.value = itemAns.note || "";
    note.addEventListener("input", ()=>{
      itemAns.note = note.value;
      a.items[itemKey] = itemAns;
      onUpdate(a);
    });
    row.appendChild(note);

    card.appendChild(row);
    itemsWrap.appendChild(card);
  });

  body.appendChild(itemsWrap);
  body.appendChild(document.createElement("hr"));

  const h = document.createElement("h2");
  h.textContent = "Ετικέτα / Θέμα ομάδας";
  body.appendChild(h);

  const labelInput = document.createElement("input");
  labelInput.type = "text";
  labelInput.placeholder = "Π.χ. Ναυτοσύνη, θρησκευτικότητα, κοινωνική φτώχεια...";
  labelInput.value = a.cluster_label || "";
  labelInput.addEventListener("input", ()=>{
    a.cluster_label = labelInput.value;
    onUpdate(a);
  });
  body.appendChild(labelInput);

  const noteArea = document.createElement("textarea");
  noteArea.placeholder = "Σχόλια για την ομάδα (προαιρετικό)";
  noteArea.value = a.cluster_note || "";
  noteArea.addEventListener("input", ()=>{
    a.cluster_note = noteArea.value;
    onUpdate(a);
  });
  body.appendChild(noteArea);

  return body;
}

function renderPairTask(task, answer, onUpdate){
  const a = answer || { relatedness:null, common_theme:"", note:"" };
  const body = document.createElement("div");
  body.className = "grid";

  const intro = document.createElement("p");
  intro.className = "muted";
  intro.textContent = "Κρίνετε τη θεματική συγγένεια του ζεύγους (1–5).";
  body.appendChild(intro);

  const card = document.createElement("div");
  card.className = "item";

  const title = document.createElement("div");
  title.className = "item-title";
  title.textContent = "Ζεύγος έργων";
  card.appendChild(title);

  const p1 = document.createElement("p");
  p1.innerHTML = `<span class="pill">A</span> <strong>${task.doc1.title || task.doc1.doc_id}</strong> <span class="muted">(${task.doc1.doc_id})</span>`;
  const p2 = document.createElement("p");
  p2.innerHTML = `<span class="pill">B</span> <strong>${task.doc2.title || task.doc2.doc_id}</strong> <span class="muted">(${task.doc2.doc_id})</span>`;
  card.appendChild(p1); card.appendChild(p2);

  const taskKey = getAnswerKey(task);

  // IMPORTANT: rerender ONLY when crossing the >=4 threshold (fixes “1 letter then stops typing”)
  card.appendChild(renderScale(`rel_${taskKey}`, a.relatedness, (val)=>{
    const prev = Number(a.relatedness || 0);
    const next = Number(val);

    a.relatedness = next;
    onUpdate(a);

    if ((prev >= 4) !== (next >= 4)) {
      render(); // show/hide the common_theme field
    }
  }));

  const note = document.createElement("input");
  note.type = "text";
  note.placeholder = "Σύντομη σημείωση (προαιρετικό)";
  note.value = a.note || "";
  note.addEventListener("input", ()=>{
    a.note = note.value;
    onUpdate(a);
  });
  card.appendChild(note);

  const shouldAskTheme = Number(a.relatedness) >= 4;
  if(shouldAskTheme){
    const h = document.createElement("h2");
    h.textContent = "Κοινό θεματικό στοιχείο (για βαθμό ≥4)";
    card.appendChild(h);

    const common = document.createElement("input");
    common.type = "text";
    common.placeholder = "1–2 φράσεις (π.χ. «θάλασσα ως μοίρα», «ηθικό δίλημμα»...)";
    common.value = a.common_theme || "";
    common.addEventListener("input", ()=>{
      a.common_theme = common.value;
      onUpdate(a);
    });
    card.appendChild(common);
  }

  body.appendChild(card);
  return body;
}

function validateTask(task, answer){
  if(task.type === "cluster"){
    if(!answer) return {ok:false, msg:"Απαντήστε στο cluster."};
    for(const it of task.items){
      const a = answer.items?.[it.doc_id];
      if(!a || !a.coherence) return {ok:false, msg:"Βάλτε βαθμό (1–5) για όλα τα έργα."};
    }
    return {ok:true, msg:""};
  }
  if(task.type === "pair"){
    if(!answer || !answer.relatedness) return {ok:false, msg:"Βάλτε βαθμό συγγένειας (1–5)."};
    if(Number(answer.relatedness) >= 4 && !String(answer.common_theme || "").trim()){
      return {ok:false, msg:"Γράψτε κοινό θεματικό στοιχείο (για ≥4)."};
    }
    return {ok:true, msg:""};
  }
  return {ok:true, msg:""};
}

function showScreen(name){
  $("screenWelcome").classList.toggle("hidden", name !== "welcome");
  $("screenTask").classList.toggle("hidden", name !== "task");
  $("screenSubmit").classList.toggle("hidden", name !== "submit");
  $("screenThanks").classList.toggle("hidden", name !== "thanks");
}

function persist(){ if(stateKey) saveState(stateKey, state); }

function updateTimingOnTaskSwitch(nextTaskKey){
  const now = Date.now();
  const prevKey = state._lastTaskKey;
  const prevEnter = state._lastTaskEnterAt;

  if(prevKey && prevEnter){
    const delta = Math.max(0, now - prevEnter);
    state.taskTimeMs[prevKey] = (state.taskTimeMs[prevKey] || 0) + delta;
  }
  state._lastTaskKey = nextTaskKey;
  state._lastTaskEnterAt = now;
}

function computeClusterBatchInfo(task){
  if(task.type !== "cluster") return null;
  const same = assignment.tasks.filter(t =>
    t.type === "cluster" &&
    t.clustering_id === task.clustering_id &&
    t.cluster_id === task.cluster_id
  );
  if(same.length <= 1) return null;

  const sorted = same.slice().sort((a,b)=>(a.batch_index ?? 0) - (b.batch_index ?? 0));
  const idx = sorted.findIndex(t => getAnswerKey(t) === getAnswerKey(task));
  return { k: idx >= 0 ? (idx+1) : null, K: sorted.length };
}

async function init(){
  expertId = qs("expert") || "E1";
  renderAdminExpertLinks();
  $("expertBadge").textContent = `Expert: ${expertId}`;

  $("consentCheck").addEventListener("change", (e)=>{
    $("btnStart").disabled = !e.target.checked;
  });

  $("btnStart").addEventListener("click", async ()=>{
    await startApp();
  });

  $("btnBack").addEventListener("click", ()=>{
    state.taskIndex = clamp(state.taskIndex - 1, 0, assignment.tasks.length);
    persist(); render();
  });

  $("btnNext").addEventListener("click", ()=>{
    const task = assignment.tasks[state.taskIndex];
    const key = getAnswerKey(task);
    const ans = state.answers[key];
    const v = validateTask(task, ans);
    if(!v.ok){ alert(v.msg); return; }
    state.taskIndex = clamp(state.taskIndex + 1, 0, assignment.tasks.length);
    persist(); render();
  });

  $("btnReview").addEventListener("click", ()=>{
    state.taskIndex = Math.max(0, assignment.tasks.length - 1);
    persist(); render();
  });

  $("btnSubmit").addEventListener("click", async ()=>{ await submit(); });

  try{
    assignment = await loadJSON(`data/assignments/${expertId}.json`);
    stateKey = storageKey(expertId, assignment.assignment_id);
    state = loadState(stateKey) || defaultState();

    if(!state.clientSessionId){
      state.clientSessionId = ensureClientSessionId();
    }

    updateBadges(expertId, state.taskIndex, assignment.tasks.length);

    if(state.submitted){
      showScreen("thanks");
    }else if(state.started){
      if(state.taskIndex >= assignment.tasks.length){
        showScreen("submit");
      }else{
        showScreen("task");
      }
      render();
    }else{
      showScreen("welcome");
    }

    persist();
  }catch(e){
    alert("Δεν βρέθηκε ανάθεση για αυτόν τον expert (λείπει data/assignments/" + expertId + ".json).");
    console.error(e);
  }
}

async function startApp(){
  if(!assignment) return;
  state.started = true;
  if(!state.startedAt) state.startedAt = nowISO();
  persist();
  showScreen("task");
  render();
}

function render(){
  if(!assignment || !state) return;

  updateBadges(expertId, state.taskIndex, assignment.tasks.length);

  if(state.taskIndex >= assignment.tasks.length){
    updateTimingOnTaskSwitch(null);
    showScreen("submit");
    return;
  }

  const task = assignment.tasks[state.taskIndex];
  const taskKey = getAnswerKey(task);

  updateTimingOnTaskSwitch(taskKey);

  $("taskType").textContent = (task.type === "cluster") ? "CLUSTER TASK" : "PAIR TASK";

  if(task.type === "cluster"){
    const bi = computeClusterBatchInfo(task);
    const extra = bi ? ` — Μέρος ${bi.k}/${bi.K}` : "";
    $("taskTitle").textContent = `Κατηγοριοποίηση ${task.clustering_id} — Cluster ${task.cluster_id}${extra}`;
  }else{
    $("taskTitle").textContent = `Κατηγοριοποίηση ${task.clustering_id} — Ζεύγος έργων`;
  }

  $("taskSubtitle").textContent = `Task ${state.taskIndex+1}/${assignment.tasks.length}`;

  const body = $("taskBody");
  body.innerHTML = "";

  const ans = state.answers[taskKey];
  const onUpdate = (newAns)=>{ state.answers[taskKey] = newAns; persist(); };

  let node=null;
  if(task.type === "cluster"){
    node = renderClusterTask(task, ans, onUpdate);
  }else{
    node = renderPairTask(task, ans, onUpdate); // no rerender on typing
  }
  body.appendChild(node);

  $("btnBack").disabled = state.taskIndex === 0;
  $("btnNext").textContent = (state.taskIndex === assignment.tasks.length - 1) ? "Ολοκλήρωση" : "Επόμενο";
}

async function submit(){
  if(state.submitted){
    showScreen("thanks");
    return;
  }

  $("btnSubmit").disabled = true;

  for(const t of assignment.tasks){
    const key = getAnswerKey(t);
    const v = validateTask(t, state.answers[key]);
    if(!v.ok){
      $("submitStatus").textContent = "Υπάρχουν ελλιπείς απαντήσεις. Επιστρέψτε για έλεγχο.";
      $("btnSubmit").disabled = false;
      return;
    }
  }

  state.finishedAt = nowISO();
  persist();

  const submissionUuid = randomId("sub");
  state.lastSubmissionUuid = submissionUuid;

  const taskDigest = assignment.tasks.map(t => {
    const base = {
      task_uid: t.task_uid || null,
      task_id: t.task_id || null,
      type: t.type,
      clustering_id: t.clustering_id
    };
    if(t.type === "cluster"){
      return {
        ...base,
        cluster_id: t.cluster_id,
        batch_index: t.batch_index ?? null,
        items: (t.items || []).map(it => ({ doc_id: it.doc_id, title: it.title || it.doc_id }))
      };
    }
    if(t.type === "pair"){
      return {
        ...base,
        pair_id: t.pair_id || null,
        doc1: { doc_id: t.doc1?.doc_id, title: t.doc1?.title || t.doc1?.doc_id },
        doc2: { doc_id: t.doc2?.doc_id, title: t.doc2?.title || t.doc2?.doc_id },
        same_cluster: !!t.same_cluster
      };
    }
    return base;
  });

  const payload = {
    expert_id: expertId,
    assignment_id: assignment.assignment_id,
    primary_clustering_id: assignment.primary_clustering_id || null,

    app_version: APP_VERSION,
    submission_uuid: submissionUuid,
    client_session_id: state.clientSessionId,

    submitted_at: nowISO(),
    started_at: state.startedAt,
    finished_at: state.finishedAt,

    meta: {
      user_agent: navigator.userAgent,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
    },

    task_time_ms: state.taskTimeMs || {},
    tasks: taskDigest,
    answers: state.answers
  };

  const data = {
    "form-name": NETLIFY_FORM_NAME,
    "expert_id": expertId,
    "assignment_id": assignment.assignment_id,
    "app_version": APP_VERSION,
    "submission_uuid": submissionUuid,
    "client_session_id": state.clientSessionId,
    "payload": JSON.stringify(payload)
  };

  $("submitStatus").textContent = "Υποβολή...";

  try{
    await submitViaNetlifyForm(data);

    state.submitted = true;
    persist();

    showScreen("thanks");
    $("submitStatus").textContent = "";
  }catch(e){
    console.error(e);
    $("submitStatus").textContent = "Σφάλμα υποβολής. Δοκιμάστε ξανά.";
    $("btnSubmit").disabled = false;
  }
}

window.addEventListener("load", init);
