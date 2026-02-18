#!/usr/bin/env python3
"""
Validate E1-E9 assignment JSON files in /opt/build/repo/site/data/assignments/.

Checks performed:
  1. Each expert has exactly 18 pair-type tasks (type=="pair")
  2. No duplicate pairs within any single expert (unordered: {doc1,doc2} == {doc2,doc1})
  3. No duplicate pairs across all experts
  4. Each expert has exactly 3 anchor tasks (is_anchor==true), one per clustering A, B, C
  5. Each expert has exactly 2 crossover tasks (assignment_role=="crossover"),
     one each for the 2 non-primary clusterings
  6. Total task count per expert is consistent (18 pairs + 17 cluster = 35)
  7. assignment_id consistency across all files
  8. Detailed report printed to stdout
"""

import json
import os
import sys
from collections import Counter, defaultdict

DATA_DIR = "/opt/build/repo/site/data/assignments"
EXPERT_IDS = [f"E{i}" for i in range(1, 10)]
EXPECTED_PAIR_COUNT = 18
EXPECTED_ANCHOR_COUNT = 3
EXPECTED_CROSSOVER_COUNT = 2
CLUSTERINGS = {"A", "B", "C"}

errors = []
warnings = []

def err(msg):
    errors.append(msg)
    print(f"  [FAIL] {msg}")

def ok(msg):
    print(f"  [ OK ] {msg}")

def warn(msg):
    warnings.append(msg)
    print(f"  [WARN] {msg}")

# ── Load all files ──────────────────────────────────────────────────────
all_data = {}
for eid in EXPERT_IDS:
    fpath = os.path.join(DATA_DIR, f"{eid}.json")
    if not os.path.isfile(fpath):
        err(f"{eid}.json not found at {fpath}")
        continue
    with open(fpath) as f:
        all_data[eid] = json.load(f)

print("=" * 72)
print("ASSIGNMENT VALIDATION REPORT")
print("=" * 72)

# ── Check 7: assignment_id consistency ──────────────────────────────────
print("\n--- Check: assignment_id consistency across all experts ---")
assignment_ids = {eid: d.get("assignment_id") for eid, d in all_data.items()}
unique_ids = set(assignment_ids.values())
if len(unique_ids) == 1:
    ok(f"All experts share the same assignment_id: {unique_ids.pop()}")
else:
    err(f"Inconsistent assignment_ids found: {assignment_ids}")

# ── Global pair tracker (for cross-expert duplicate check) ──────────────
global_pairs = {}  # frozenset -> expert_id

for eid in EXPERT_IDS:
    if eid not in all_data:
        continue
    data = all_data[eid]
    tasks = data.get("tasks", [])
    primary = data.get("primary_clustering_id")

    print(f"\n{'─' * 72}")
    print(f"Expert: {eid}  |  primary_clustering_id: {primary}")
    print(f"{'─' * 72}")

    # ── Check 8: expert_id matches filename ─────────────────────────────
    if data.get("expert_id") != eid:
        err(f"expert_id field '{data.get('expert_id')}' does not match filename '{eid}'")
    else:
        ok(f"expert_id field matches filename ({eid})")

    # ── Separate tasks by type ──────────────────────────────────────────
    pair_tasks = [t for t in tasks if t.get("type") == "pair"]
    cluster_tasks = [t for t in tasks if t.get("type") == "cluster"]
    other_tasks = [t for t in tasks if t.get("type") not in ("pair", "cluster")]

    # ── Check 1: exactly 18 pair tasks ──────────────────────────────────
    print(f"\n  --- Pair tasks (type=='pair') ---")
    if len(pair_tasks) == EXPECTED_PAIR_COUNT:
        ok(f"Pair task count = {len(pair_tasks)} (expected {EXPECTED_PAIR_COUNT})")
    else:
        err(f"{eid}: Pair task count = {len(pair_tasks)}, expected {EXPECTED_PAIR_COUNT}")

    # ── Check 2: no duplicate pairs within this expert ──────────────────
    print(f"\n  --- Intra-expert duplicate pair check ---")
    local_pairs = {}
    local_dup = False
    for t in pair_tasks:
        d1 = t["doc1"]["doc_id"]
        d2 = t["doc2"]["doc_id"]
        pair_key = frozenset([d1, d2])
        if pair_key in local_pairs:
            err(f"{eid}: Duplicate pair within expert: {{{d1}, {d2}}} "
                f"(task_ids {local_pairs[pair_key]} and {t['task_id']})")
            local_dup = True
        else:
            local_pairs[pair_key] = t.get("task_id", "?")
    if not local_dup:
        ok(f"No duplicate pairs within {eid} ({len(local_pairs)} unique pairs)")

    # ── Check 3 (accumulate): cross-expert duplicates ───────────────────
    for t in pair_tasks:
        d1 = t["doc1"]["doc_id"]
        d2 = t["doc2"]["doc_id"]
        pair_key = frozenset([d1, d2])
        if pair_key in global_pairs:
            # Will be reported after the loop
            pass
        global_pairs.setdefault(pair_key, []).append(eid)

    # ── Check 4: exactly 3 anchors, one per clustering ──────────────────
    print(f"\n  --- Anchor tasks (is_anchor==true) ---")
    anchor_tasks = [t for t in tasks if t.get("is_anchor") is True]
    if len(anchor_tasks) == EXPECTED_ANCHOR_COUNT:
        ok(f"Anchor task count = {len(anchor_tasks)} (expected {EXPECTED_ANCHOR_COUNT})")
    else:
        err(f"{eid}: Anchor task count = {len(anchor_tasks)}, expected {EXPECTED_ANCHOR_COUNT}")

    anchor_clusterings = sorted(t.get("clustering_id") for t in anchor_tasks)
    if set(anchor_clusterings) == CLUSTERINGS:
        ok(f"Anchors cover all clusterings: {anchor_clusterings}")
    else:
        err(f"{eid}: Anchor clusterings = {anchor_clusterings}, expected one each of A, B, C")

    # ── Check 5: exactly 2 crossover tasks for the 2 non-primary clusterings
    print(f"\n  --- Crossover tasks (assignment_role=='crossover') ---")
    crossover_tasks = [t for t in tasks if t.get("assignment_role") == "crossover"]
    if len(crossover_tasks) == EXPECTED_CROSSOVER_COUNT:
        ok(f"Crossover task count = {len(crossover_tasks)} (expected {EXPECTED_CROSSOVER_COUNT})")
    else:
        err(f"{eid}: Crossover task count = {len(crossover_tasks)}, expected {EXPECTED_CROSSOVER_COUNT}")

    crossover_clusterings = sorted(t.get("clustering_id") for t in crossover_tasks)
    expected_crossover_clusterings = sorted(CLUSTERINGS - {primary})
    if crossover_clusterings == expected_crossover_clusterings:
        ok(f"Crossover clusterings = {crossover_clusterings} "
           f"(non-primary, given primary={primary})")
    else:
        err(f"{eid}: Crossover clusterings = {crossover_clusterings}, "
            f"expected {expected_crossover_clusterings} (primary={primary})")

    # ── Check 6: total task count ───────────────────────────────────────
    print(f"\n  --- Total task count ---")
    total = len(tasks)
    expected_total = 35  # 18 pair + 17 cluster (12 primary + 3 anchor + 2 crossover)
    print(f"  Breakdown: {len(pair_tasks)} pair + {len(cluster_tasks)} cluster = {total} total")
    if total == expected_total:
        ok(f"Total task count = {total} (expected {expected_total})")
    else:
        err(f"{eid}: Total task count = {total}, expected {expected_total}")

    if other_tasks:
        warn(f"{eid}: Found {len(other_tasks)} tasks with unexpected type: "
             f"{[t.get('type') for t in other_tasks]}")

    # ── Check 8b: task_id prefix consistency ────────────────────────────
    print(f"\n  --- task_id consistency ---")
    bad_prefix = [t for t in tasks if not t.get("task_id", "").startswith(f"{eid}_")]
    if not bad_prefix:
        ok(f"All task_ids start with '{eid}_'")
    else:
        err(f"{eid}: {len(bad_prefix)} task(s) have task_id not prefixed with '{eid}_': "
            f"{[t.get('task_id') for t in bad_prefix[:5]]}")

    # Check task_id uniqueness within expert
    task_ids = [t.get("task_id") for t in tasks]
    dup_ids = [tid for tid, cnt in Counter(task_ids).items() if cnt > 1]
    if not dup_ids:
        ok(f"All {len(task_ids)} task_ids are unique within {eid}")
    else:
        err(f"{eid}: Duplicate task_ids: {dup_ids}")

    # ── Role breakdown summary ──────────────────────────────────────────
    role_counts = Counter(t.get("assignment_role") for t in tasks)
    print(f"\n  Role breakdown: {dict(role_counts)}")

# ── Check 3 (report): cross-expert duplicate pairs ─────────────────────
print(f"\n{'=' * 72}")
print("--- Check: Cross-expert duplicate pairs ---")
cross_dups = {k: v for k, v in global_pairs.items() if len(v) > 1}
if not cross_dups:
    ok(f"No duplicate pairs across experts ({len(global_pairs)} globally unique pairs)")
else:
    err(f"Found {len(cross_dups)} pair(s) assigned to multiple experts:")
    for pair_key, experts in sorted(cross_dups.items(), key=lambda x: str(x)):
        docs = sorted(pair_key)
        print(f"    {{{docs[0]}, {docs[1]}}} -> {experts}")

# ── Final summary ──────────────────────────────────────────────────────
print(f"\n{'=' * 72}")
print("SUMMARY")
print(f"{'=' * 72}")
print(f"  Experts validated : {len(all_data)}/{len(EXPERT_IDS)}")
print(f"  Total pairs       : {len(global_pairs)}")
print(f"  Errors            : {len(errors)}")
print(f"  Warnings          : {len(warnings)}")
if errors:
    print("\n  ERRORS:")
    for e in errors:
        print(f"    - {e}")
if warnings:
    print("\n  WARNINGS:")
    for w in warnings:
        print(f"    - {w}")

if errors:
    print(f"\nRESULT: FAIL ({len(errors)} error(s))")
    sys.exit(1)
else:
    print(f"\nRESULT: PASS (all checks passed)")
    sys.exit(0)
