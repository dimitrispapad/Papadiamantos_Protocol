# Papadiamantis Clustering Expert Evaluation (Netlify-ready)

Static web app (HTML/CSS/JS) for expert evaluation of **three** alternative clusterings (A/B/C).

**Task types**
- **Cluster task:** coherence (1–5) per item + misplaced flag + cluster label/notes.
- **Pair task:** relatedness (1–5) for pairs. If **>= 4**, the UI asks for the **common thematic element**.

**Data collection**
- Uses **Netlify Forms** (no external DB required).
- Submits one JSON payload per expert session.

## Quick start (local)
```bash
python -m http.server 8000
# open: http://localhost:8000/?expert=E1
```

## Deploy on Netlify
**Drag & drop**
1. Upload the folder/zip in Netlify.
2. Visit: `https://YOUR_SITE.netlify.app/?expert=E1`
3. Submissions: Netlify → Site → Forms → `papadiamantis-eval`.

**GitHub**
1. Push these files to a repo.
2. Netlify → Import from Git → deploy.

## Plug in your real clusterings
Option A (manual): create
- `data/clusterings/A.json`, `B.json`, `C.json`
with:
```json
{ "clustering_id":"A", "clusters":[{"cluster_id":"0","items":[{"doc_id":"x.txt","title":"x.txt"}]}] }
```

Option B (recommended): drop your cluster inventories (txt) to:
- `data/clusterings_raw/TFIDF_ONLY.txt`
- `data/clusterings_raw/SEMANTIC_ONLY.txt`
- `data/clusterings_raw/HYBRID_50_50.txt`

Then:
```bash
python scripts/generate_assignments.py       --tfidf data/clusterings_raw/TFIDF_ONLY.txt       --semantic data/clusterings_raw/SEMANTIC_ONLY.txt       --hybrid data/clusterings_raw/HYBRID_50_50.txt       --out data
```

This creates:
- `data/clusterings/A.json`, `B.json`, `C.json`
- `data/assignments/E1.json ... E9.json`

## Export + parse submissions
Netlify → Forms → Export CSV, then:
```bash
python scripts/parse_netlify_export.py --csv netlify_export.csv --out parsed_out
```
Outputs:
- `parsed_out/item_ratings.csv`
- `parsed_out/cluster_ratings.csv`
- `parsed_out/pair_ratings.csv`
