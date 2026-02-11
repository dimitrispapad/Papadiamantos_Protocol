#!/usr/bin/env python3
"""Generate A/B/C clusterings and E1..E9 assignments from text inventories.

Input inventories: text files with lines like:
  Cluster 0 (n=...):
    - file1.txt
    - file2.txt

Output (under --out):
  clusterings/A.json, B.json, C.json
  assignments/E1.json ... E9.json

Default plan:
  - 9 experts E1..E9
  - 3 primary per clustering
  - anchors + crossover clusters + balanced pairs
"""

import argparse, json, os, random, re
from typing import List, Dict

def parse_inventory(path: str) -> List[Dict]:
  with open(path, "r", encoding="utf-8") as f:
    lines = [ln.rstrip("\n") for ln in f]

  clusters = []
  current = None
  rx_cluster = re.compile(r"^\s*cluster\s+([\-]?\d+)", re.IGNORECASE)
  rx_bullet  = re.compile(r"^\s*[-•]\s*(.+)$")

  for ln in lines:
    m = rx_cluster.search(ln)
    if m:
      if current: clusters.append(current)
      current = {"cluster_id": str(m.group(1)), "items":[]}
      continue
    if current:
      b = rx_bullet.match(ln)
      if b:
        doc = b.group(1).strip().strip(" ,;")
        if doc:
          current["items"].append({"doc_id": doc, "title": doc})
  if current: clusters.append(current)

  clusters = [c for c in clusters if c["items"]]
  if not clusters:
    raise ValueError(f"Could not parse clusters from {path}")
  return clusters

def sample_items(cluster: Dict, m: int):
  items = cluster["items"]
  return items[:] if len(items) <= m else random.sample(items, m)

def build_cluster_tasks(cid: str, clusters: List[Dict], m: int):
  return [{"type":"cluster","clustering_id":cid,"cluster_id":c["cluster_id"],"items":sample_items(c,m)} for c in clusters]

def build_pairs(cid: str, clusters: List[Dict], n_pairs: int):
  pos, neg = [], []
  flat = [(c["cluster_id"], it) for c in clusters for it in c["items"]]
  if len(flat) < 4: return []

  eligible = [c for c in clusters if len(c["items"]) >= 2] or clusters

  for _ in range(n_pairs//2):
    c = random.choice(eligible)
    if len(c["items"]) >= 2:
      a,b = random.sample(c["items"], 2)
      pos.append((a,b,True))
  cids = [c["cluster_id"] for c in clusters]
  for _ in range(n_pairs - len(pos)):
    c1,c2 = random.sample(cids, 2)
    a = random.choice([it for cid,it in flat if cid==c1])
    b = random.choice([it for cid,it in flat if cid==c2])
    neg.append((a,b,False))

  pairs = pos + neg
  random.shuffle(pairs)

  tasks=[]
  for i,(a,b,same) in enumerate(pairs, start=1):
    tasks.append({
      "type":"pair","clustering_id":cid,"pair_id":f"{cid}_p{i}",
      "doc1":a,"doc2":b,"same_cluster":bool(same)
    })
  return tasks

def ensure_dir(p): os.makedirs(p, exist_ok=True)

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--tfidf", required=True)
  ap.add_argument("--semantic", required=True)
  ap.add_argument("--hybrid", required=True)
  ap.add_argument("--out", required=True)
  ap.add_argument("--seed", type=int, default=42)
  ap.add_argument("--m_per_cluster", type=int, default=4)
  ap.add_argument("--anchor_clusters_per_clustering", type=int, default=2)
  ap.add_argument("--crossover_clusters_per_other", type=int, default=2)
  ap.add_argument("--pairs_per_expert", type=int, default=24)
  args = ap.parse_args()

  random.seed(args.seed)

  raw_map = {
    "A": ("TFIDF_ONLY", args.tfidf),
    "B": ("SEMANTIC_ONLY", args.semantic),
    "C": ("HYBRID_50_50", args.hybrid),
  }

  clustering_objs={}
  for cid,(name,path) in raw_map.items():
    clusters = parse_inventory(path)
    clustering_objs[cid] = {"clustering_id":cid,"name":f"Clustering {cid} (blind)","source_name":name,"clusters":clusters}

  out_clusterings = os.path.join(args.out, "clusterings")
  ensure_dir(out_clusterings)
  for cid,obj in clustering_objs.items():
    with open(os.path.join(out_clusterings, f"{cid}.json"), "w", encoding="utf-8") as f:
      json.dump(obj, f, ensure_ascii=False, indent=2)

  clustering_tasks={}
  for cid,obj in clustering_objs.items():
    all_clusters = obj["clusters"]
    clustering_tasks[cid] = {
      "cluster_tasks_all": build_cluster_tasks(cid, all_clusters, args.m_per_cluster),
      "pairs_pool": build_pairs(cid, all_clusters, 900)
    }

  experts = [f"E{i}" for i in range(1,10)]
  primary = {"A":experts[0:3], "B":experts[3:6], "C":experts[6:9]}

  anchors={}
  for cid in ["A","B","C"]:
    pool = clustering_tasks[cid]["cluster_tasks_all"]
    anchors[cid] = random.sample(pool, k=min(args.anchor_clusters_per_clustering, len(pool)))

  out_assign = os.path.join(args.out, "assignments")
  ensure_dir(out_assign)

  def task_key(t): return (t["type"], t.get("clustering_id"), t.get("cluster_id"), t.get("pair_id"))

  for e in experts:
    primary_cid = next(cid for cid,ls in primary.items() if e in ls)
    tasks=[]
    tasks += clustering_tasks[primary_cid]["cluster_tasks_all"]

    seen=set()
    for cid in ["A","B","C"]:
      for t in anchors[cid]:
        k=task_key(t)
        if k not in seen:
          tasks.append(t); seen.add(k)

    others=[cid for cid in ["A","B","C"] if cid!=primary_cid]
    for oc in others:
      pool = clustering_tasks[oc]["cluster_tasks_all"]
      anchor_ids=set(t["cluster_id"] for t in anchors[oc])
      pool2=[t for t in pool if t["cluster_id"] not in anchor_ids] or pool
      tasks += random.sample(pool2, k=min(args.crossover_clusters_per_other, len(pool2)))

    pairs=[]
    per=max(2, args.pairs_per_expert//3)
    for cid in ["A","B","C"]:
      pool = clustering_tasks[cid]["pairs_pool"]
      pairs += pool[:per]
      clustering_tasks[cid]["pairs_pool"] = pool[per:]
    while len(pairs) < args.pairs_per_expert:
      cid=random.choice(["A","B","C"])
      pool=clustering_tasks[cid]["pairs_pool"]
      if not pool: break
      pairs.append(pool.pop(0))
      clustering_tasks[cid]["pairs_pool"]=pool

    tasks += pairs
    random.shuffle(tasks)
    for i,t in enumerate(tasks, start=1):
      t["task_id"]=f"{e}_{i:04d}"

    assignment = {
      "assignment_id": f"pap_eval_seed{args.seed}_m{args.m_per_cluster}_pairs{args.pairs_per_expert}",
      "expert_id": e,
      "created_at": "AUTO",
      "tasks": tasks
    }
    with open(os.path.join(out_assign, f"{e}.json"), "w", encoding="utf-8") as f:
      json.dump(assignment, f, ensure_ascii=False, indent=2)

  print("OK: wrote clusterings + assignments to", args.out)

if __name__ == "__main__":
  main()
