# Papadiamantis Clustering Expert Evaluation (Netlify-ready)

Static web app (HTML/CSS/JS) for blinded expert evaluation of **three** alternative clusterings of Papadiamantis short stories (A/B/C).

The interface presents **two task types** (cluster screens + pair screens), saves progress locally in the browser, and submits a single structured JSON payload to **Netlify Forms**.

---

## What experts do (2 task types)

### T1 — Cluster task (item-level)
Experts see a small set of works sampled from one cluster and provide:
- **Coherence rating (1–5)** for each work (how well it fits the group)
- **Misplaced flag** (binary outlier marker)
- Optional: **cluster label** (1–5 words) and short notes

### T2 — Pair task (pairwise relatedness)
Experts rate a pair of works on:
- **Relatedness (1–5)**
- If **≥ 4**, the UI prompts for a short **common thematic element** (1–2 sentences)

---

## How experts access the study

Each expert receives a personalized link:

- `https://<YOUR_DOMAIN>/?expert=E1`
- `https://<YOUR_DOMAIN>/?expert=E2`
- …
- `https://<YOUR_DOMAIN>/?expert=E9`

Experts are **blinded**: clusterings are shown only as **A/B/C** (mapping to TF–IDF, semantic, hybrid is hidden during rating).

Progress is saved in the expert’s browser (localStorage), so they can refresh and continue.

---

## Data collection and integrity

- Submissions are stored via **Netlify Forms** under the form name: `papadiamantis-eval`
- Each submission includes:
  - `expert_id`, `assignment_id`, `app_version`
  - timestamps (`started_at`, `submitted_at`, `finished_at`)
  - stable per-task identifiers (**`task_uid`**) and all answers
  - idempotency fields: **`client_session_id`** + **`submission_uuid`**  
    (used to deduplicate accidental re-submissions during preprocessing)

**Important:** tasks are keyed by `task_uid` (stable across reordering/regeneration), avoiding collisions that can occur with sequential task IDs.

---

## Repository structure (publish directory)

Netlify publishes the folder:

- `papadiamantis-eval-netlify/`

Key paths:
- `papadiamantis-eval-netlify/index.html`
- `papadiamantis-eval-netlify/assets/` (UI logic + CSS)
- `papadiamantis-eval-netlify/data/clusterings_raw/` (input inventories)
- `papadiamantis-eval-netlify/data/clusterings/` (A/B/C JSON used by the app)
- `papadiamantis-eval-netlify/data/assignments/` (E1..E9 assignment JSON + manifest)
- `papadiamantis-eval-netlify/scripts/` (generation + parsing utilities)

---

## Quick start (local)

Serve the repo root and open the **correct subpath**:

```bash
python3 -m http.server 8000
# open:
# http://localhost:8000/papadiamantis-eval-netlify/?expert=E1
