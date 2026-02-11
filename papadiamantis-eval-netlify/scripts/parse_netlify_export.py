#!/usr/bin/env python3
"""Parse Netlify Forms CSV export (with JSON payload) into tidy CSVs."""

import argparse, csv, json, os

def ensure_dir(p): os.makedirs(p, exist_ok=True)

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--csv", required=True)
  ap.add_argument("--out", required=True)
  args = ap.parse_args()
  ensure_dir(args.out)

  item_rows=[]; cluster_rows=[]; pair_rows=[]

  with open(args.csv, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
      payload_raw = row.get("payload") or row.get("Payload") or ""
      if not payload_raw.strip():
        continue
      try:
        payload = json.loads(payload_raw)
      except Exception:
        continue

      expert_id = payload.get("expert_id")
      assignment_id = payload.get("assignment_id")
      submitted_at = payload.get("submitted_at")
      tasks = payload.get("tasks", [])
      answers = payload.get("answers", {})
      task_by_id = {t.get("task_id"): t for t in tasks}

      for task_id, ans in answers.items():
        t = task_by_id.get(task_id, {})
        if t.get("type") == "cluster":
          clustering_id = t.get("clustering_id"); cluster_id = t.get("cluster_id")
          cluster_rows.append({
            "expert_id": expert_id, "assignment_id": assignment_id, "submitted_at": submitted_at,
            "task_id": task_id, "clustering_id": clustering_id, "cluster_id": cluster_id,
            "cluster_label": (ans.get("cluster_label") or "").strip(),
            "cluster_note": (ans.get("cluster_note") or "").strip(),
          })
          items = ans.get("items") or {}
          for doc_id, ia in items.items():
            item_rows.append({
              "expert_id": expert_id, "assignment_id": assignment_id, "submitted_at": submitted_at,
              "task_id": task_id, "clustering_id": clustering_id, "cluster_id": cluster_id,
              "doc_id": doc_id, "coherence": ia.get("coherence"),
              "misplaced": int(bool(ia.get("misplaced"))),
              "note": (ia.get("note") or "").strip()
            })
        elif t.get("type") == "pair":
          pair_rows.append({
            "expert_id": expert_id, "assignment_id": assignment_id, "submitted_at": submitted_at,
            "task_id": task_id, "clustering_id": t.get("clustering_id"),
            "pair_id": t.get("pair_id"),
            "doc1": (t.get("doc1") or {}).get("doc_id"),
            "doc2": (t.get("doc2") or {}).get("doc_id"),
            "same_cluster": int(bool(t.get("same_cluster"))),
            "relatedness": ans.get("relatedness"),
            "common_theme": (ans.get("common_theme") or "").strip(),
            "note": (ans.get("note") or "").strip(),
          })

  def write_csv(path, rows):
    if not rows: return
    with open(path, "w", encoding="utf-8", newline="") as f:
      w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
      w.writeheader()
      for r in rows: w.writerow(r)

  write_csv(os.path.join(args.out, "item_ratings.csv"), item_rows)
  write_csv(os.path.join(args.out, "cluster_ratings.csv"), cluster_rows)
  write_csv(os.path.join(args.out, "pair_ratings.csv"), pair_rows)
  print("OK:", len(item_rows), "item;", len(cluster_rows), "cluster;", len(pair_rows), "pair rows")

if __name__ == "__main__":
  main()
