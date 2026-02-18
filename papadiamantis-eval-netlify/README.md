# Papadiamantis Clustering Expert Evaluation (Netlify-ready)

Static web app (HTML/CSS/JS) for blinded expert evaluation of **three** alternative clusterings of Papadiamantis short stories (A/B/C).

The interface presents **two task types** (cluster screens + pair screens), saves progress locally in the browser, and submits a single structured JSON payload to **Netlify Forms**.

---

## Clustering parameters

| Blind ID | K (clusters) | N (documents) |
|----------|-------------|---------------|
| A        | 9           | 172           |
| B        | 14          | 172           |
| C        | 7           | 172           |

The A/B/C-to-method mapping is kept internal and is **not shown to experts**.

- **Assignment ID:** `pap_eval_seed42_m5_pairs18_v2`
- **Seed:** 42

Public hosting does not expose method-labeled artifacts (blinding enforced).

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

Progress is saved in the expert's browser (localStorage), so they can refresh and continue.

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

## Repository structure

Netlify publishes the `site/` folder, which contains **only** the web app and assignment JSONs needed by experts. Unblinded clustering artifacts remain in the repository but are **not** in the publish directory.

**Publish directory** (`site/`):
- `site/index.html`
- `site/assets/` (UI logic + CSS + image)
- `site/data/assignments/` (E1..E9 assignment JSON + manifest)

**Internal data** (not published):
- `papadiamantis-eval-netlify/data/clusterings/` (A/B/C JSON with method names)
- `papadiamantis-eval-netlify/data/clusterings_raw/` (raw clustering text files)
- `papadiamantis-eval-netlify/scripts/` (generation + parsing utilities)

---

## Validation

A regression validator is provided to ensure the package remains consistent:

```bash
python scripts/validate_eval_package.py
```

The validator checks:
1. No forbidden strings (method names) in the publish directory
2. Pair uniqueness within each expert and across all experts
3. Clustering integrity (K, N, doc-set equality)

---

## Quick start (local)

Serve the `site/` folder directly:

```bash
cd site && python3 -m http.server 8000
# open: http://localhost:8000/?expert=E1
```

Or use Netlify CLI:

```bash
netlify dev
# open: http://localhost:8888/?expert=E1
```
