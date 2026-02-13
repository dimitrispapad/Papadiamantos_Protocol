#!/usr/bin/env python3
"""
Parse Netlify Forms CSV export (JSON payload) into tidy CSVs.

Upgrades (v2):
- Supports answers keyed by task_uid (preferred) or task_id (fallback).
- Dedupe submissions (keep latest per (expert_id, assignment_id, client_session_id)).
- Exports:
  - submissions.csv (kept + duplicates marked)
  - item_ratings.csv (T1 item-level)
  - cluster_ratings.csv (T1 cluster-level)
  - pair_ratings.csv (T2 pair-level)
"""

import argparse, csv, json, os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def ensure_dir(p: str):
  os.makedirs(p, exist_ok=True)


def parse_iso_ts(s: Optional[str]) -> Optional[datetime]:
  if not s or not str(s).strip():
    return None
  s = str(s).strip()
  try:
    # handle Z
    if s.endswith("Z"):
      s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
  except Exception:
    return None


def best_row_timestamp(row: Dict[str, str], payload: Dict[str, Any]) -> datetime:
  """
  Determine a stable timestamp for ordering submissions.
  Priority: payload.submitted_at > CSV created/created_at > now(UTC, as fallback).
  """
  # from payload
  t = parse_iso_ts(payload.get("submitted_at")) or parse_iso_ts(payload.get("finished_at"))
  if t:
    return t

  # from common Netlify CSV columns (varies)
  for k in ["Created", "created_at", "created", "Timestamp", "timestamp", "Date", "date"]:
    if k in row:
      t2 = parse_iso_ts(row.get(k))
      if t2:
        return t2

  # worst-case fallback: deterministic-ish but safe
  return datetime.now(timezone.utc)


def get_payload_raw(row: Dict[str, str]) -> str:
  # Netlify export column names can vary
  for k in ["payload", "Payload", "PAYLOAD"]:
    if k in row and (row.get(k) or "").strip():
      return row.get(k) or ""
  return ""


def safe_json_loads(s: str) -> Optional[Dict[str, Any]]:
  try:
    obj = json.loads(s)
    if isinstance(obj, dict):
      return obj
    return None
  except Exception:
    return None


def norm_str(x: Any) -> str:
  return ("" if x is None else str(x)).strip()


def dedupe_key(payload: Dict[str, Any]) -> Tuple[str, str, str]:
  expert_id = norm_str(payload.get("expert_id")) or "UNKNOWN_EXPERT"
  assignment_id = norm_str(payload.get("assignment_id")) or "UNKNOWN_ASSIGNMENT"
  client_session_id = norm_str(payload.get("client_session_id")) or "NO_SESSION"
  return (expert_id, assignment_id, client_session_id)


def build_task_index(tasks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
  """
  Map keys -> task object for both task_uid and task_id.
  """
  idx: Dict[str, Dict[str, Any]] = {}
  for t in tasks or []:
    tu = norm_str(t.get("task_uid"))
    ti = norm_str(t.get("task_id"))
    if tu:
      idx[tu] = t
    if ti and ti not in idx:
      idx[ti] = t
  return idx


def write_csv(path: str, rows: List[Dict[str, Any]]):
  if not rows:
    return
  # stable field order: union of keys (some rows may have extras)
  fieldnames = []
  seen = set()
  for r in rows:
    for k in r.keys():
      if k not in seen:
        fieldnames.append(k)
        seen.add(k)

  with open(path, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
      w.writerow(r)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--csv", required=True, help="Netlify Forms export CSV")
  ap.add_argument("--out", required=True, help="Output folder for tidy CSVs")
  ap.add_argument("--keep_duplicates", action="store_true",
                  help="If set, keep all submissions (still marks duplicates in submissions.csv). "
                       "If not set, only the latest per dedupe key is used for ratings outputs.")
  args = ap.parse_args()

  ensure_dir(args.out)

  submissions_raw: List[Dict[str, Any]] = []
  parse_errors = 0

  with open(args.csv, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
      payload_raw = get_payload_raw(row)
      if not payload_raw.strip():
        continue

      payload = safe_json_loads(payload_raw)
      if not payload:
        parse_errors += 1
        continue

      # normalize core fields
      payload["expert_id"] = norm_str(payload.get("expert_id"))
      payload["assignment_id"] = norm_str(payload.get("assignment_id"))
      payload["app_version"] = norm_str(payload.get("app_version"))
      payload["submission_uuid"] = norm_str(payload.get("submission_uuid"))
      payload["client_session_id"] = norm_str(payload.get("client_session_id"))

      ts = best_row_timestamp(row, payload)
      submissions_raw.append({
        "row": row,
        "payload": payload,
        "ts": ts,
        "dedupe_key": dedupe_key(payload),
      })

  # Sort by timestamp ascending, then keep LAST as canonical
  submissions_raw.sort(key=lambda x: x["ts"])

  # Dedupe map: key -> index of kept record
  kept_idx_by_key: Dict[Tuple[str, str, str], int] = {}
  for i, rec in enumerate(submissions_raw):
    kept_idx_by_key[rec["dedupe_key"]] = i  # last one wins

  # Also guard against duplicated submission_uuid (rare but possible)
  kept_idx_by_uuid: Dict[str, int] = {}
  for i, rec in enumerate(submissions_raw):
    su = norm_str(rec["payload"].get("submission_uuid"))
    if su:
      kept_idx_by_uuid[su] = i  # last wins

  submissions_rows: List[Dict[str, Any]] = []
  kept_records: List[Dict[str, Any]] = []

  for i, rec in enumerate(submissions_raw):
    p = rec["payload"]
    key = rec["dedupe_key"]
    is_latest_for_key = (kept_idx_by_key.get(key) == i)

    su = norm_str(p.get("submission_uuid"))
    is_latest_for_uuid = True
    if su:
      is_latest_for_uuid = (kept_idx_by_uuid.get(su) == i)

    kept = bool(is_latest_for_key and is_latest_for_uuid)
    if kept:
      kept_records.append(rec)

    submissions_rows.append({
      "kept": int(kept),
      "reason": "latest_for_key_and_uuid" if kept else "duplicate_or_older",
      "expert_id": p.get("expert_id"),
      "assignment_id": p.get("assignment_id"),
      "client_session_id": p.get("client_session_id") or "",
      "submission_uuid": p.get("submission_uuid") or "",
      "app_version": p.get("app_version") or "",
      "primary_clustering_id": p.get("primary_clustering_id") or "",
      "submitted_at": p.get("submitted_at") or "",
      "started_at": p.get("started_at") or "",
      "finished_at": p.get("finished_at") or "",
      "ts_used": rec["ts"].isoformat(),
    })

  # Choose which records to expand into ratings
  records_for_ratings = submissions_raw if args.keep_duplicates else kept_records

  item_rows: List[Dict[str, Any]] = []
  cluster_rows: List[Dict[str, Any]] = []
  pair_rows: List[Dict[str, Any]] = []

  for rec in records_for_ratings:
    p = rec["payload"]
    expert_id = p.get("expert_id")
    assignment_id = p.get("assignment_id")
    submitted_at = p.get("submitted_at") or rec["ts"].isoformat()
    app_version = p.get("app_version") or ""
    submission_uuid = p.get("submission_uuid") or ""
    client_session_id = p.get("client_session_id") or ""
    primary_clustering_id = p.get("primary_clustering_id") or ""

    tasks = p.get("tasks", []) or []
    answers = p.get("answers", {}) or {}
    task_time_ms = p.get("task_time_ms", {}) or {}

    task_by_key = build_task_index(tasks)

    # answers keys are task_uid (preferred) or task_id (fallback)
    for task_key, ans in answers.items():
      t = task_by_key.get(task_key, {}) or {}
      ttype = t.get("type")

      clustering_id = t.get("clustering_id")
      role = t.get("assignment_role") or ""

      time_ms = task_time_ms.get(task_key)
      if time_ms is None:
        # also try via task_uid/task_id alternative
        tu = norm_str(t.get("task_uid"))
        ti = norm_str(t.get("task_id"))
        time_ms = task_time_ms.get(tu) if tu else None
        if time_ms is None and ti:
          time_ms = task_time_ms.get(ti)

      if ttype == "cluster":
        cluster_id = t.get("cluster_id")
        batch_index = t.get("batch_index")

        cluster_rows.append({
          "expert_id": expert_id,
          "assignment_id": assignment_id,
          "primary_clustering_id": primary_clustering_id,
          "submitted_at": submitted_at,
          "app_version": app_version,
          "client_session_id": client_session_id,
          "submission_uuid": submission_uuid,

          "task_key": task_key,
          "task_uid": t.get("task_uid") or "",
          "task_id": t.get("task_id") or "",
          "assignment_role": role,

          "clustering_id": clustering_id,
          "cluster_id": cluster_id,
          "batch_index": batch_index if batch_index is not None else "",

          "cluster_label": norm_str(ans.get("cluster_label")),
          "cluster_note": norm_str(ans.get("cluster_note")),
          "task_time_ms": time_ms if time_ms is not None else "",
        })

        items = ans.get("items") or {}
        for doc_id, ia in items.items():
          item_rows.append({
            "expert_id": expert_id,
            "assignment_id": assignment_id,
            "primary_clustering_id": primary_clustering_id,
            "submitted_at": submitted_at,
            "app_version": app_version,
            "client_session_id": client_session_id,
            "submission_uuid": submission_uuid,

            "task_key": task_key,
            "task_uid": t.get("task_uid") or "",
            "task_id": t.get("task_id") or "",
            "assignment_role": role,

            "clustering_id": clustering_id,
            "cluster_id": cluster_id,
            "batch_index": batch_index if batch_index is not None else "",

            "doc_id": doc_id,
            "coherence": ia.get("coherence"),
            "misplaced": int(bool(ia.get("misplaced"))),
            "note": norm_str(ia.get("note")),
            "task_time_ms": time_ms if time_ms is not None else "",
          })

      elif ttype == "pair":
        pair_rows.append({
          "expert_id": expert_id,
          "assignment_id": assignment_id,
          "primary_clustering_id": primary_clustering_id,
          "submitted_at": submitted_at,
          "app_version": app_version,
          "client_session_id": client_session_id,
          "submission_uuid": submission_uuid,

          "task_key": task_key,
          "task_uid": t.get("task_uid") or "",
          "task_id": t.get("task_id") or "",
          "assignment_role": role,

          "clustering_id": clustering_id,
          "pair_id": t.get("pair_id") or "",
          "doc1": (t.get("doc1") or {}).get("doc_id") if isinstance(t.get("doc1"), dict) else "",
          "doc2": (t.get("doc2") or {}).get("doc_id") if isinstance(t.get("doc2"), dict) else "",
          "same_cluster": int(bool(t.get("same_cluster"))),
          "relatedness": ans.get("relatedness"),
          "common_theme": norm_str(ans.get("common_theme")),
          "note": norm_str(ans.get("note")),
          "task_time_ms": time_ms if time_ms is not None else "",
        })

      else:
        # Unknown task types are ignored (future-proof)
        pass

  # Write outputs
  write_csv(os.path.join(args.out, "submissions.csv"), submissions_rows)
  write_csv(os.path.join(args.out, "item_ratings.csv"), item_rows)
  write_csv(os.path.join(args.out, "cluster_ratings.csv"), cluster_rows)
  write_csv(os.path.join(args.out, "pair_ratings.csv"), pair_rows)

  kept_n = sum(int(r["kept"]) for r in submissions_rows)
  print("OK:")
  print(f"  submissions parsed: {len(submissions_rows)} (kept={kept_n}, duplicates={len(submissions_rows)-kept_n})")
  print(f"  parse errors (payload JSON): {parse_errors}")
  print(f"  item rows: {len(item_rows)}")
  print(f"  cluster rows: {len(cluster_rows)}")
  print(f"  pair rows: {len(pair_rows)}")
  if not args.keep_duplicates:
    print("  ratings outputs are based on kept submissions only (latest per expert/assignment/session).")


if __name__ == "__main__":
  main()
