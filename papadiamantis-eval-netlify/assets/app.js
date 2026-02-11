const APP_VERSION = "0.1.0";
const STORAGE_PREFIX = "pap_eval_v1";

function qs(name){ return new URL(window.location.href).searchParams.get(name); }
function $(id){ return document.getElementById(id); }
function clamp(n, lo, hi){ return Math.max(lo, Math.min(hi, n)); }
function nowISO(){ return new Date().toISOString(); }

function encodeForm(data){
  const params = new URLSearchParams();
  Object.entries(data).forEach(([k,v]) => params.append(k, v));
  return params.toString();
}

async function loadJSON(path){
  const r = await fetch(path, {cache:"no-store"});
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
  return { started:false, taskIndex:0, answers:{}, startedAt:null, finishedAt:null };
}

function saveState(key, state){ localStorage.setItem(key, JSON.stringify(state)); }
function loadState(key){
  const raw = localStorage.getItem(key);
  if(!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
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

    card.appendChild(renderScale(`coh_${task.task_id}_${itemKey}`, itemAns.coherence, (val)=>{
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

  card.appendChild(renderScale(`rel_${task.task_id}`, a.relatedness, (val)=>{
    a.relatedness = val;
    onUpdate(a);
    render(); // refresh to show/hide common theme
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

  function render(){ /* placeholder; caller rerenders */ }
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

let assignment=null, expertId=null, stateKey=null, state=null;

async function init(){
  expertId = qs("expert") || "E1";
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
    const ans = state.answers[task.task_id];
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
    updateBadges(expertId, state.taskIndex, assignment.tasks.length);
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
  $("screenWelcome").classList.add("hidden");
  $("screenTask").classList.remove("hidden");
  render();
}

function persist(){ if(stateKey) saveState(stateKey, state); }

function render(){
  if(!assignment || !state) return;
  updateBadges(expertId, state.taskIndex, assignment.tasks.length);

  if(state.taskIndex >= assignment.tasks.length){
    $("screenTask").classList.add("hidden");
    $("screenSubmit").classList.remove("hidden");
    $("screenThanks").classList.add("hidden");
    return;
  }else{
    $("screenSubmit").classList.add("hidden");
    $("screenThanks").classList.add("hidden");
  }

  const task = assignment.tasks[state.taskIndex];
  $("taskType").textContent = (task.type === "cluster") ? "CLUSTER TASK" : "PAIR TASK";
  $("taskTitle").textContent = (task.type === "cluster")
    ? `Κατηγοριοποίηση ${task.clustering_id} — Cluster ${task.cluster_id}`
    : `Κατηγοριοποίηση ${task.clustering_id} — Ζεύγος έργων`;
  $("taskSubtitle").textContent = `Task ${state.taskIndex+1}/${assignment.tasks.length}`;

  const body = $("taskBody");
  body.innerHTML = "";

  const ans = state.answers[task.task_id];
  const onUpdate = (newAns)=>{ state.answers[task.task_id] = newAns; persist(); };

  let node=null;
  if(task.type === "cluster"){
    node = renderClusterTask(task, ans, onUpdate);
  }else{
    node = renderPairTask(task, ans, (newAns)=>{ onUpdate(newAns); render(); });
  }
  body.appendChild(node);

  $("btnBack").disabled = state.taskIndex === 0;
  $("btnNext").textContent = (state.taskIndex === assignment.tasks.length - 1) ? "Ολοκλήρωση" : "Επόμενο";
}

async function submit(){
  for(const t of assignment.tasks){
    const v = validateTask(t, state.answers[t.task_id]);
    if(!v.ok){
      $("submitStatus").textContent = "Υπάρχουν ελλιπείς απαντήσεις. Επιστρέψτε για έλεγχο.";
      return;
    }
  }

  state.finishedAt = nowISO();
  persist();

  const payload = {
    expert_id: expertId,
    assignment_id: assignment.assignment_id,
    app_version: APP_VERSION,
    submitted_at: nowISO(),
    started_at: state.startedAt,
    finished_at: state.finishedAt,
    meta: { user_agent: navigator.userAgent, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
    tasks: assignment.tasks,
    answers: state.answers
  };

  const data = {
    "form-name": "papadiamantis-eval",
    "expert_id": expertId,
    "assignment_id": assignment.assignment_id,
    "app_version": APP_VERSION,
    "payload": JSON.stringify(payload)
  };

  $("submitStatus").textContent = "Υποβολή...";
  try{
    const r = await fetch("/", {
      method:"POST",
      headers: {"Content-Type":"application/x-www-form-urlencoded"},
      body: encodeForm(data)
    });
    if(!r.ok){
      $("submitStatus").textContent = "Σφάλμα υποβολής. Δοκιμάστε ξανά.";
      return;
    }
    $("screenSubmit").classList.add("hidden");
    $("screenThanks").classList.remove("hidden");
    $("submitStatus").textContent = "";
  }catch(e){
    console.error(e);
    $("submitStatus").textContent = "Σφάλμα δικτύου. Δοκιμάστε ξανά.";
  }
}

window.addEventListener("load", init);
