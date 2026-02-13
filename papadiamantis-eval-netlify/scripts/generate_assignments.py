#!/usr/bin/env python3
"""
Generate A/B/C clusterings and E1..E9 assignments from text inventories.

Key upgrades (v2):
- Coverage-first T1: every doc appears exactly once per clustering (in batches of m items).
- Anchor tasks are a subset of T1 tasks and are added exactly once per expert (no duplicates).
- Unique T2 pairs (pos/neg) with dedupe.
- Deterministic task_uids for reproducibility.
- Validation checks to catch duplicates / coverage gaps.

Outputs (under --out):
  clusterings/A.json, B.json, C.json
  assignments/E1.json ... E9.json
  assignments/manifest.json
"""

import argparse, json, os, random, re, copy
from typing import List, Dict, Tuple, Set, Optional


# ----------------------------
# Parsing
# ----------------------------

def parse_inventory(path: str) -> List[Dict]:
  """
  Parses inventories with blocks like:
    Cluster 0 (n=...):
      - file1.txt
      - file2.txt
  """
  with open(path, "r", encoding="utf-8") as f:
    lines = [ln.rstrip("\n") for ln in f]

  clusters = []
  current = None
  rx_cluster = re.compile(r"^\s*cluster\s+([\-]?\d+)", re.IGNORECASE)
  rx_bullet  = re.compile(r"^\s*[-•]\s*(.+)$")

  for ln in lines:
    m = rx_cluster.search(ln)
    if m:
      if current:
        clusters.append(current)
      current = {"cluster_id": str(m.group(1)), "items": []}
      continue

    if current:
      b = rx_bullet.match(ln)
      if b:
        doc = b.group(1).strip().strip(" ,;")
        if doc:
          current["items"].append({"doc_id": doc, "title": doc})

  if current:
    clusters.append(current)

  clusters = [c for c in clusters if c["items"]]
  if not clusters:
    raise ValueError(f"Could not parse clusters from {path}")
  return clusters


def ensure_dir(p: str):
  os.makedirs(p, exist_ok=True)


def _all_doc_ids(clusters: List[Dict]) -> List[str]:
  return [it["doc_id"] for c in clusters for it in c["items"]]


def validate_same_corpus(A: List[Dict], B: List[Dict], C: List[Dict]) -> None:
  sA, sB, sC = set(_all_doc_ids(A)), set(_all_doc_ids(B)), set(_all_doc_ids(C))
  if not (sA == sB == sC):
    onlyA = sorted(list(sA - sB))[:10]
    onlyB = sorted(list(sB - sA))[:10]
    onlyC = sorted(list(sC - sA))[:10]
    raise ValueError(
      "Corpus mismatch across clusterings.\n"
      f"|A|={len(sA)} |B|={len(sB)} |C|={len(sC)}\n"
      f"Example only-in-A: {onlyA}\n"
      f"Example only-in-B: {onlyB}\n"
      f"Example only-in-C: {onlyC}\n"
    )


# ----------------------------
# T1 Coverage Tasks
# ----------------------------

def _chunk(lst: List[Dict], m: int) -> List[List[Dict]]:
  return [lst[i:i+m] for i in range(0, len(lst), m)]


def make_t1_coverage_tasks(cid: str, clusters: List[Dict], m: int, seed: int) -> List[Dict]:
  """
  Creates cluster tasks that cover every item exactly once per clustering.
  Each task is a batch of up to m items drawn without replacement from a single cluster.
  """
  rng = random.Random(seed)
  tasks = []
  for c in clusters:
    items = copy.deepcopy(c["items"])
    rng.shuffle(items)
    batches = _chunk(items, m)
    for b_ix, batch in enumerate(batches):
      task_uid = f"{cid}_c{c['cluster_id']}_b{b_ix:03d}"
      tasks.append({
        "type": "cluster",
        "task_uid": task_uid,
        "clustering_id": cid,
        "cluster_id": c["cluster_id"],
        "batch_index": b_ix,
        "items": batch,
        "t1_mode": "item_fit"  # future-proof if you add intruder later
      })
  rng.shuffle(tasks)
  return tasks


def pick_anchor_tasks(tasks: List[Dict], n_anchors: int, seed: int) -> List[Dict]:
  """
  Picks anchor tasks with cluster diversity (round-robin across clusters).
  """
  if n_anchors <= 0:
    return []

  rng = random.Random(seed)
  by_cluster: Dict[str, List[Dict]] = {}
  for t in tasks:
    by_cluster.setdefault(t["cluster_id"], []).append(t)

  for cid in by_cluster:
    rng.shuffle(by_cluster[cid])

  cluster_ids = sorted(by_cluster.keys())
  anchors = []
  k = 0
  while len(anchors) < n_anchors and cluster_ids:
    cid = cluster_ids[k % len(cluster_ids)]
    if by_cluster[cid]:
      anchors.append(by_cluster[cid].pop())
    k += 1
    if k > 10_000:
      break

  # mark
  for t in anchors:
    t["is_anchor"] = True
  return anchors


def remove_tasks_by_uid(tasks: List[Dict], uids: Set[str]) -> List[Dict]:
  return [t for t in tasks if t["task_uid"] not in uids]


# ----------------------------
# T2 Pair Tasks (unique)
# ----------------------------

def build_unique_pairs(cid: str, clusters: List[Dict], n_pairs: int, seed: int, pos_frac: float = 0.5) -> List[Dict]:
  """
  Builds a pool of unique pair tasks.
  pos pairs sampled within cluster, neg pairs across different clusters.
  Dedupe by unordered (doc1, doc2).
  """
  rng = random.Random(seed)

  # cluster_id -> items
  cmap: Dict[str, List[Dict]] = {c["cluster_id"]: c["items"][:] for c in clusters}
  cluster_ids = list(cmap.keys())
  flat = [(c_id, it) for c_id, items in cmap.items() for it in items]
  if len(flat) < 4:
    return []

  def norm_key(a: Dict, b: Dict) -> Tuple[str, str]:
    x, y = a["doc_id"], b["doc_id"]
    return (x, y) if x < y else (y, x)

  want_pos = int(round(n_pairs * pos_frac))
  want_neg = n_pairs - want_pos

  seen: Set[Tuple[str, str]] = set()
  tasks: List[Dict] = []

  # helper to add
  def try_add_pair(a: Dict, b: Dict, same: bool) -> bool:
    if a["doc_id"] == b["doc_id"]:
      return False
    k = norm_key(a, b)
    if k in seen:
      return False
    seen.add(k)
    task_uid = f"{cid}_pair_{len(tasks)+1:04d}"
    tasks.append({
      "type": "pair",
      "task_uid": task_uid,
      "clustering_id": cid,
      "pair_id": task_uid,
      "doc1": copy.deepcopy(a),
      "doc2": copy.deepcopy(b),
      "same_cluster": bool(same)
    })
    return True

  # positive
  pos_tries = 0
  while sum(1 for t in tasks if t["same_cluster"]) < want_pos and pos_tries < n_pairs * 200:
    pos_tries += 1
    c = rng.choice([c for c in clusters if len(c["items"]) >= 2] or clusters)
    a, b = rng.sample(c["items"], 2)
    try_add_pair(a, b, True)

  # negative
  neg_tries = 0
  while sum(1 for t in tasks if not t["same_cluster"]) < want_neg and neg_tries < n_pairs * 400:
    neg_tries += 1
    c1, c2 = rng.sample(cluster_ids, 2)
    a = rng.choice(cmap[c1])
    b = rng.choice(cmap[c2])
    try_add_pair(a, b, False)

  rng.shuffle(tasks)
  return tasks


# ----------------------------
# Assignment design
# ----------------------------

def round_robin_split(items: List[Dict], buckets: List[str], seed: int) -> Dict[str, List[Dict]]:
  rng = random.Random(seed)
  items2 = items[:]
  rng.shuffle(items2)
  out = {b: [] for b in buckets}
  for i, it in enumerate(items2):
    out[buckets[i % len(buckets)]].append(it)
  return out


def clone_task(t: Dict) -> Dict:
  return copy.deepcopy(t)


def validate_no_duplicate_task_uids(assignment_tasks: List[Dict], expert_id: str) -> None:
  uids = [t.get("task_uid") for t in assignment_tasks]
  if len(uids) != len(set(uids)):
    # find examples
    seen = set()
    dups = []
    for u in uids:
      if u in seen:
        dups.append(u)
      seen.add(u)
    raise ValueError(f"[{expert_id}] Duplicate task_uid(s) in assignment: {dups[:10]}")


def validate_t1_coverage(tasks: List[Dict], clusters: List[Dict], cid: str) -> None:
  """
  Ensures each doc appears exactly once in T1 coverage tasks (before anchors are reused across experts).
  """
  expected = sorted(_all_doc_ids(clusters))
  got = []
  for t in tasks:
    if t["type"] == "cluster":
      got.extend([it["doc_id"] for it in t["items"]])
  expected_set = set(expected)
  got_set = set(got)

  if expected_set != got_set:
    miss = sorted(list(expected_set - got_set))[:10]
    extra = sorted(list(got_set - expected_set))[:10]
    raise ValueError(
      f"[{cid}] T1 coverage mismatch. expected={len(expected_set)} got={len(got_set)} "
      f"missing(ex)={miss} extra(ex)={extra}"
    )

  # Check multiplicity
  counts = {}
  for d in got:
    counts[d] = counts.get(d, 0) + 1
  bad = [d for d,c in counts.items() if c != 1]
  if bad:
    raise ValueError(f"[{cid}] T1 coverage has docs with count != 1 (ex): {bad[:10]}")


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--tfidf", required=True)
  ap.add_argument("--semantic", required=True)
  ap.add_argument("--hybrid", required=True)
  ap.add_argument("--out", required=True)

  ap.add_argument("--seed", type=int, default=42)

  # NOTE: previously m_per_cluster was "sample size". Now it's "items per T1 task batch".
  ap.add_argument("--m_per_cluster", type=int, default=5)

  # NOTE: previously named "anchor_clusters..." but it effectively means "anchor TASKS per clustering".
  ap.add_argument("--anchor_clusters_per_clustering", type=int, default=1)

  # NOTE: crossover tasks per other clustering (not clusters).
  ap.add_argument("--crossover_clusters_per_other", type=int, default=1)

  ap.add_argument("--pairs_per_expert", type=int, default=18)

  # internal: how many pairs to generate as a pool per clustering
  ap.add_argument("--pairs_pool_size", type=int, default=800)

  args = ap.parse_args()

  raw_map = {
    "A": ("TFIDF_ONLY", args.tfidf),
    "B": ("SEMANTIC_ONLY", args.semantic),
    "C": ("HYBRID_50_50", args.hybrid),
  }

  # Parse clusterings
  clustering_objs = {}
  for cid, (name, path) in raw_map.items():
    clusters = parse_inventory(path)
    clustering_objs[cid] = {
      "clustering_id": cid,
      "name": f"Clustering {cid} (blind)",
      "source_name": name,
      "clusters": clusters
    }

  # Validate same corpus across A/B/C
  validate_same_corpus(
    clustering_objs["A"]["clusters"],
    clustering_objs["B"]["clusters"],
    clustering_objs["C"]["clusters"],
  )

  # Write clusterings
  out_clusterings = os.path.join(args.out, "clusterings")
  ensure_dir(out_clusterings)
  for cid, obj in clustering_objs.items():
    with open(os.path.join(out_clusterings, f"{cid}.json"), "w", encoding="utf-8") as f:
      json.dump(obj, f, ensure_ascii=False, indent=2)

  # Build T1 coverage tasks + anchors
  t1_all = {}
  t1_anchors = {}
  t1_pool = {}
  for cid in ["A", "B", "C"]:
    clusters = clustering_objs[cid]["clusters"]
    t1_tasks = make_t1_coverage_tasks(cid, clusters, args.m_per_cluster, seed=args.seed + ord(cid))
    validate_t1_coverage(t1_tasks, clusters, cid)

    anchors = pick_anchor_tasks(t1_tasks, n_anchors=min(args.anchor_clusters_per_clustering, len(t1_tasks)),
                                seed=args.seed + 1000 + ord(cid))
    anchor_uids = set(t["task_uid"] for t in anchors)
    pool = remove_tasks_by_uid(t1_tasks, anchor_uids)

    # mark pool
    for t in pool:
      t["is_anchor"] = False

    t1_all[cid] = t1_tasks
    t1_anchors[cid] = anchors
    t1_pool[cid] = pool

  # Experts and primaries (fixed to E1..E9 and 3 per clustering)
  experts = [f"E{i}" for i in range(1, 10)]
  primary = {"A": experts[0:3], "B": experts[3:6], "C": experts[6:9]}

  # Distribute T1 pool tasks among primaries (round-robin) => full coverage achieved by primaries
  primary_alloc = {}
  for cid in ["A", "B", "C"]:
    primary_alloc[cid] = round_robin_split(
      t1_pool[cid],
      buckets=primary[cid],
      seed=args.seed + 2000 + ord(cid)
    )

  # Build T2 pair pools (unique)
  pair_pool = {}
  for cid in ["A", "B", "C"]:
    clusters = clustering_objs[cid]["clusters"]
    pair_pool[cid] = build_unique_pairs(
      cid, clusters, n_pairs=args.pairs_pool_size,
      seed=args.seed + 3000 + ord(cid),
      pos_frac=0.5
    )

  # Prepare output folders
  out_assign = os.path.join(args.out, "assignments")
  ensure_dir(out_assign)

  # Manifest (reproducibility + analysis convenience)
  manifest = {
    "assignment_id": f"pap_eval_seed{args.seed}_m{args.m_per_cluster}_pairs{args.pairs_per_expert}",
    "seed": args.seed,
    "items_per_t1_task": args.m_per_cluster,
    "anchors_per_clustering": args.anchor_clusters_per_clustering,
    "crossover_tasks_per_other": args.crossover_clusters_per_other,
    "pairs_per_expert": args.pairs_per_expert,
    "primaries": primary,
    "notes": {
      "t1": "Coverage-first batches: each doc appears exactly once per clustering in T1 base pool; anchors are reused across experts.",
      "t2": "Unique pairs per clustering from a global pool; allocated by popping (no repeats across experts until pool exhausted)."
    }
  }
  with open(os.path.join(out_assign, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

  # Helper: pop k pairs safely
  def pop_pairs(cid: str, k: int) -> List[Dict]:
    out = []
    while k > 0 and pair_pool[cid]:
      out.append(pair_pool[cid].pop(0))
      k -= 1
    return out

  # Build each expert assignment
  for e in experts:
    primary_cid = next(cid for cid, ls in primary.items() if e in ls)

    tasks: List[Dict] = []

    # 1) Primary T1 (coverage pool share)
    for t in primary_alloc[primary_cid][e]:
      tt = clone_task(t)
      tt["assignment_role"] = "primary"
      tasks.append(tt)

    # 2) Anchors (all clusterings, for agreement) — add once
    for cid in ["A", "B", "C"]:
      for t in t1_anchors[cid]:
        tt = clone_task(t)
        tt["assignment_role"] = "anchor"
        tasks.append(tt)

    # 3) Crossover T1 (small sample from other clusterings, excluding anchors)
    others = [cid for cid in ["A", "B", "C"] if cid != primary_cid]
    rng = random.Random(args.seed + 4000 + int(e[1:]) * 17)
    for oc in others:
      pool = t1_pool[oc]  # excludes anchors by construction
      if not pool:
        continue
      k = min(args.crossover_clusters_per_other, len(pool))
      sample = rng.sample(pool, k=k)
      for t in sample:
        tt = clone_task(t)
        tt["assignment_role"] = "crossover"
        tasks.append(tt)

    # 4) Pair tasks (balanced across A/B/C as much as possible)
    per = max(2, args.pairs_per_expert // 3)
    pairs = []
    for cid in ["A", "B", "C"]:
      pairs += pop_pairs(cid, per)
    while len(pairs) < args.pairs_per_expert:
      cid = rng.choice(["A", "B", "C"])
      more = pop_pairs(cid, 1)
      if not more:
        break
      pairs += more

    for t in pairs:
      tt = clone_task(t)
      tt["assignment_role"] = "pair"
      tasks.append(tt)

    # Final: shuffle but deterministically per expert (stable, reproducible)
    rng.shuffle(tasks)

    # Add per-expert task_id (ordering)
    for i, t in enumerate(tasks, start=1):
      t["task_id"] = f"{e}_{i:04d}"

    # Validate no duplicate task_uids within expert
    validate_no_duplicate_task_uids(tasks, e)

    assignment = {
      "assignment_id": manifest["assignment_id"],
      "expert_id": e,
      "created_at": "AUTO",
      "primary_clustering_id": primary_cid,
      "tasks": tasks
    }

    with open(os.path.join(out_assign, f"{e}.json"), "w", encoding="utf-8") as f:
      json.dump(assignment, f, ensure_ascii=False, indent=2)

  print("OK: wrote clusterings + assignments to", args.out)
  print("T1 tasks per clustering (total/anchors/pool):")
  for cid in ["A","B","C"]:
    print(
      f"  {cid}: total={len(t1_all[cid])}, anchors={len(t1_anchors[cid])}, pool={len(t1_pool[cid])}"
    )
  print("Example expected time sanity:")
  # Rough: T1 tasks per primary expert
  for cid in ["A","B","C"]:
    sizes = [len(primary_alloc[cid][e]) for e in primary[cid]]
    print(f"  {cid} primary T1 per expert: {sizes} (mean={sum(sizes)/len(sizes):.1f})")
  print("Pair pool remaining:", {cid: len(pair_pool[cid]) for cid in ["A","B","C"]})


if __name__ == "__main__":
  main()
