#!/usr/bin/env python3
"""
Regression validator for the Papadiamantis expert-evaluation package.

Checks:
  1. Blinding: no forbidden strings inside the publish directory.
  2. Pair uniqueness: within each expert and across all experts.
  3. Clustering integrity: A/B/C doc-set equality and K/N values.

Usage:
  python scripts/validate_eval_package.py
"""

import json
import os
import sys

# ── Configuration ────────────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLISH_DIR = os.path.join(REPO_ROOT, "site")
CLUSTERING_DIR = os.path.join(REPO_ROOT, "papadiamantis-eval-netlify", "data", "clusterings")
ASSIGNMENT_DIR = os.path.join(PUBLISH_DIR, "data", "assignments")

FORBIDDEN_STRINGS = ["TFIDF_ONLY", "SEMANTIC_ONLY", "HYBRID_50_50", "source_name"]

EXPECTED = {
    "A": {"K": 9, "N": 172},
    "B": {"K": 14, "N": 172},
    "C": {"K": 7, "N": 172},
}

PAIRS_PER_EXPERT = 18
EXPERTS = [f"E{i}" for i in range(1, 10)]

# ── Helpers ──────────────────────────────────────────────────────────────────

failures = []
passes = []


def record(check_id, ok, detail=""):
    if ok:
        passes.append((check_id, detail))
    else:
        failures.append((check_id, detail))


def norm_pair(d1, d2):
    return tuple(sorted([d1, d2]))


# ── 1. Blinding check ───────────────────────────────────────────────────────

def check_blinding():
    """Ensure no forbidden strings exist in any file under the publish directory."""
    hits = []
    if not os.path.isdir(PUBLISH_DIR):
        record("BLINDING", False, f"Publish directory does not exist: {PUBLISH_DIR}")
        return

    for root, dirs, files in os.walk(PUBLISH_DIR):
        for fname in files:
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, PUBLISH_DIR)

            # Check filename
            for fs in FORBIDDEN_STRINGS:
                if fs in fname:
                    hits.append(f"Filename contains '{fs}': {rel}")

            # Check file content (text files only)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for fs in FORBIDDEN_STRINGS:
                    if fs in content:
                        hits.append(f"Content contains '{fs}': {rel}")
            except Exception:
                pass  # skip binary files

    if hits:
        record("BLINDING", False, "; ".join(hits))
    else:
        record("BLINDING", True, "No forbidden strings found in publish directory")


# ── 2. Pair uniqueness ──────────────────────────────────────────────────────

def check_pairs():
    """Check pair uniqueness within and across experts."""
    all_expert_pairs = {}  # expert -> list of norm pairs

    for eid in EXPERTS:
        fpath = os.path.join(ASSIGNMENT_DIR, f"{eid}.json")
        if not os.path.isfile(fpath):
            record(f"PAIRS_{eid}", False, f"Assignment file missing: {fpath}")
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        pairs = []
        for t in data.get("tasks", []):
            if t.get("type") == "pair":
                p = norm_pair(t["doc1"]["doc_id"], t["doc2"]["doc_id"])
                pairs.append(p)

        # Check count
        if len(pairs) != PAIRS_PER_EXPERT:
            record(f"PAIRS_{eid}_COUNT", False,
                   f"{eid} has {len(pairs)} pairs, expected {PAIRS_PER_EXPERT}")
        else:
            record(f"PAIRS_{eid}_COUNT", True, f"{eid}: {len(pairs)} pairs")

        # Check within-expert uniqueness
        seen = set()
        dupes = []
        for p in pairs:
            if p in seen:
                dupes.append(p)
            seen.add(p)

        if dupes:
            record(f"PAIRS_{eid}_UNIQUE", False,
                   f"{eid} has {len(dupes)} within-expert duplicate(s): {dupes}")
        else:
            record(f"PAIRS_{eid}_UNIQUE", True, f"{eid}: no within-expert duplicates")

        all_expert_pairs[eid] = pairs

    # Cross-expert uniqueness
    pair_owners = {}
    for eid, pairs in all_expert_pairs.items():
        for p in pairs:
            pair_owners.setdefault(p, []).append(eid)

    cross_dupes = {p: owners for p, owners in pair_owners.items() if len(owners) > 1}
    if cross_dupes:
        details = "; ".join(f"{p}: {owners}" for p, owners in cross_dupes.items())
        record("PAIRS_CROSS_EXPERT", False, f"{len(cross_dupes)} cross-expert duplicate(s): {details}")
    else:
        record("PAIRS_CROSS_EXPERT", True, "No cross-expert pair duplicates")


# ── 3. Clustering integrity ─────────────────────────────────────────────────

def check_clusterings():
    """Validate A/B/C doc-set equality, K, and N."""
    doc_sets = {}

    for cid, expected in EXPECTED.items():
        fpath = os.path.join(CLUSTERING_DIR, f"{cid}.json")
        if not os.path.isfile(fpath):
            record(f"CLUSTERING_{cid}", False, f"Clustering file missing: {fpath}")
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        clusters = data.get("clusters", [])
        K = len(clusters)
        all_docs = []
        for c in clusters:
            for item in c.get("items", []):
                all_docs.append(item["doc_id"])

        N = len(all_docs)
        unique = len(set(all_docs))

        ok = True
        issues = []

        if K != expected["K"]:
            ok = False
            issues.append(f"K={K}, expected {expected['K']}")
        if N != expected["N"]:
            ok = False
            issues.append(f"N={N}, expected {expected['N']}")
        if unique != N:
            ok = False
            issues.append(f"unique={unique}, N={N} (duplicates detected)")

        detail = f"{cid}: K={K}, N={N}, unique={unique}"
        if issues:
            detail += " — " + "; ".join(issues)
        record(f"CLUSTERING_{cid}", ok, detail)

        doc_sets[cid] = set(all_docs)

    # Cross-clustering doc-set equality
    ids = list(doc_sets.keys())
    if len(ids) >= 2:
        all_equal = all(doc_sets[ids[0]] == doc_sets[c] for c in ids[1:])
        if all_equal:
            record("CLUSTERING_DOCSET_EQ", True,
                   f"Doc-sets equal across {', '.join(ids)} ({len(doc_sets[ids[0]])} docs)")
        else:
            diffs = []
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    only_a = doc_sets[a] - doc_sets[b]
                    only_b = doc_sets[b] - doc_sets[a]
                    if only_a or only_b:
                        diffs.append(f"{a} vs {b}: only in {a}={len(only_a)}, only in {b}={len(only_b)}")
            record("CLUSTERING_DOCSET_EQ", False, "; ".join(diffs))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Papadiamantis Evaluation Package — Regression Validator")
    print("=" * 70)
    print()

    check_blinding()
    check_pairs()
    check_clusterings()

    print("RESULTS")
    print("-" * 70)

    for check_id, detail in passes:
        print(f"  PASS  {check_id}: {detail}")

    for check_id, detail in failures:
        print(f"  FAIL  {check_id}: {detail}")

    print("-" * 70)

    if failures:
        print(f"\n*** {len(failures)} FAILURE(S) — NOT READY TO SEND ***\n")
        sys.exit(1)
    else:
        print(f"\n*** ALL {len(passes)} CHECKS PASSED — READY TO SEND ***\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
