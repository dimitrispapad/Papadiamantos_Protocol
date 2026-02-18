import json
from pathlib import Path
from itertools import combinations

NEW_ASSIGNMENT_ID = "pap_eval_seed42_m5_pairs18_v2"

# Original layout (before "site/" build step)
ASSIGN_DIR_CANDIDATES = [
    Path("papadiamantis-eval-netlify/data/assignments"),
    Path("_private/data/assignments"),
]
CLUSTER_DIR_CANDIDATES = [
    Path("papadiamantis-eval-netlify/data/clusterings"),
    Path("_private/data/clusterings"),
]

PATCHES = [
    {"expert": "E5", "task_id": "E5_0015", "clustering_id": "C", "want_same_cluster": True},
    {"expert": "E9", "task_id": "E9_0009", "clustering_id": "A", "want_same_cluster": True},
]

def first_existing(paths):
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"None of these paths exist: {paths}")

def load_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def unordered_pair(a, b):
    return tuple(sorted((a, b)))

def clustering_same_cluster_pairs(clustering_path: Path):
    data = load_json(clustering_path)
    pairs = []
    # expected: data["clusters"] = [{"cluster_id":..., "items":[{"doc_id":...}, ...]}, ...]
    for c in data.get("clusters", []):
        docs = [it["doc_id"] for it in c.get("items", []) if "doc_id" in it]
        for d1, d2 in combinations(docs, 2):
            pairs.append((d1, d2))
    return pairs

def collect_used_pairs(assign_dir: Path):
    used_global = set()
    per_expert = {}
    for efile in sorted(assign_dir.glob("E*.json")):
        e = load_json(efile)
        used = set()
        for t in e.get("tasks", []):
            if t.get("type") == "pair":
                d1 = t["doc1"]["doc_id"]
                d2 = t["doc2"]["doc_id"]
                used.add(unordered_pair(d1, d2))
                used_global.add(unordered_pair(d1, d2))
        per_expert[efile.stem] = used
    return used_global, per_expert

def patch_one(assign_dir: Path, cluster_dir: Path, expert_id: str, task_id: str, clustering_id: str, want_same_cluster: bool, used_global: set):
    expert_path = assign_dir / f"{expert_id}.json"
    e = load_json(expert_path)

    # find task
    idx = None
    for i, t in enumerate(e.get("tasks", [])):
        if t.get("task_id") == task_id:
            idx = i
            break
    if idx is None:
        raise KeyError(f"{expert_id}: task_id {task_id} not found")

    t = e["tasks"][idx]
    if t.get("type") != "pair":
        raise ValueError(f"{expert_id}:{task_id} is not a pair task")
    if t.get("clustering_id") != clustering_id:
        raise ValueError(f"{expert_id}:{task_id} clustering_id is {t.get('clustering_id')} not {clustering_id}")

    old_pair = unordered_pair(t["doc1"]["doc_id"], t["doc2"]["doc_id"])
    old_uid = t.get("task_uid", "")

    # candidate same-cluster pairs come from within-cluster combinations → same_cluster=True by construction
    clustering_path = cluster_dir / f"{clustering_id}.json"
    if not clustering_path.exists():
        raise FileNotFoundError(f"Missing clustering file: {clustering_path}")

    candidates = clustering_same_cluster_pairs(clustering_path)

    replacement = None
    for a, b in candidates:
        p = unordered_pair(a, b)
        if p in used_global:
            continue
        # since candidates are within-cluster, same_cluster is true
        if want_same_cluster and True is not True:
            continue
        replacement = (a, b)
        break

    if replacement is None:
        raise RuntimeError(f"No unused replacement pair found for clustering {clustering_id}")

    new_d1, new_d2 = replacement

    # apply patch
    t["patched_from"] = {
        "task_uid": old_uid,
        "doc_pair": list(old_pair),
    }
    # keep task_id same, keep ordering
    t["doc1"] = {"doc_id": new_d1, "title": new_d1}
    t["doc2"] = {"doc_id": new_d2, "title": new_d2}
    t["same_cluster"] = True

    # bump uid/pair_id
    t["task_uid"] = f"{old_uid}_v2" if old_uid else f"{clustering_id}_pair_v2"
    if "pair_id" in t:
        t["pair_id"] = f"{t['pair_id']}_v2"

    # update global used set: remove old, add new
    used_global.discard(old_pair)
    used_global.add(unordered_pair(new_d1, new_d2))

    save_json(expert_path, e)
    print(f"[OK] Patched {expert_id} {task_id}: {old_pair} -> {unordered_pair(new_d1, new_d2)}")

def main():
    assign_dir = first_existing(ASSIGN_DIR_CANDIDATES)
    cluster_dir = first_existing(CLUSTER_DIR_CANDIDATES)
    manifest_path = assign_dir / "manifest.json"

    used_global, _ = collect_used_pairs(assign_dir)

    # patch targets
    for p in PATCHES:
        patch_one(assign_dir, cluster_dir, p["expert"], p["task_id"], p["clustering_id"], p["want_same_cluster"], used_global)

    # unify assignment_id across experts
    for efile in sorted(assign_dir.glob("E*.json")):
        e = load_json(efile)
        e["assignment_id"] = NEW_ASSIGNMENT_ID
        save_json(efile, e)

    # update manifest
    if manifest_path.exists():
        m = load_json(manifest_path)
        m["assignment_id"] = NEW_ASSIGNMENT_ID
        note = "v2: patched duplicate pair tasks (E5:E5_0015, E9:E9_0009) and unified assignment_id across experts."

        notes = m.get("notes")
        if notes is None:
            m["notes"] = [note]
        elif isinstance(notes, list):
            notes.append(note)
            m["notes"] = notes
        elif isinstance(notes, dict):
            notes["v2_patch"] = note
            m["notes"] = notes
        elif isinstance(notes, str):
            m["notes"] = [notes, note]
        else:
            m["notes"] = [str(notes), note]

        save_json(manifest_path, m)
    else:
        print("[WARN] manifest.json not found; skipping manifest update.")

    print("[DONE] patch_assignments_v2 complete.")

if __name__ == "__main__":
    main()
