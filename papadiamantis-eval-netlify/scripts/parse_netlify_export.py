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
