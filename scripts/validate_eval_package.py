import json
import re
from pathlib import Path

FORBIDDEN = ["TFIDF_ONLY", "SEMANTIC_ONLY", "HYBRID_50_50", "source_name"]

def fail(msg):
    print("FAIL:", msg)
    raise SystemExit(1)

def ok(msg):
    print("PASS:", msg)

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")

def main():
    # 1) netlify.toml publish="site"
    nt = Path("netlify.toml")
    if not nt.exists():
        fail("netlify.toml missing at repo root")
    t = read_text(nt)
    m = re.search(r'publish\s*=\s*"([^"]+)"', t)
    if not m:
        fail("Could not parse publish= from netlify.toml")
    publish = m.group(1).strip()
    if publish != "site":
        fail(f'publish must be "site", got "{publish}"')
    ok('netlify.toml publish="site"')

    site = Path("site")
    if not site.exists():
        fail("site/ directory missing (run scripts/build_site.py)")

    # 2) forbidden strings absent from site/
    bad = []
    for p in site.rglob("*"):
        if p.is_file():
            txt = read_text(p)
            for s in FORBIDDEN:
                if s in txt:
                    bad.append((str(p), s))
    if bad:
        fail(f"Forbidden strings found in site/: {bad[:5]} (showing first 5)")
    ok("No forbidden strings in site/")

    # 3) no clusterings/raw/scripts in site
    for blocked in ["data/clusterings", "data/clusterings_raw", "scripts"]:
        if (site / blocked).exists():
            fail(f"Blocked path exists in site/: {blocked}")
    ok("No blocked paths inside site/")

    # 4) assignments integrity
    adir = site / "data" / "assignments"
    if not adir.exists():
        fail("site/data/assignments missing")

    experts = [f"E{i}" for i in range(1, 10)]
    assigns = {}
    for e in experts:
        p = adir / f"{e}.json"
        if not p.exists():
            fail(f"Missing assignment: {p}")
        assigns[e] = json.loads(read_text(p))

    # counts + duplicates
    global_pairs = set()
    for e, data in assigns.items():
        tasks = data.get("tasks", [])
        pairs = [t for t in tasks if t.get("type") == "pair"]
        if len(pairs) != 18:
            fail(f"{e}: expected 18 pair tasks, got {len(pairs)}")

        # anchors and crossovers
        anchors = [t for t in tasks if t.get("assignment_role") == "anchor"]
        if len(anchors) != 3:
            fail(f"{e}: expected 3 anchor tasks, got {len(anchors)}")
        cross = [t for t in tasks if t.get("assignment_role") == "crossover" and t.get("type") == "cluster"]
        if len(cross) != 2:
            fail(f"{e}: expected 2 crossover cluster tasks, got {len(cross)}")

        local = set()
        for t in pairs:
            d1 = t["doc1"]["doc_id"]
            d2 = t["doc2"]["doc_id"]
            pair = tuple(sorted((d1, d2)))
            if pair in local:
                fail(f"{e}: duplicate pair within expert: {pair}")
            local.add(pair)
            if pair in global_pairs:
                fail(f"Global duplicate pair across experts (unordered): {pair}")
            global_pairs.add(pair)

    if len(global_pairs) != 162:
        fail(f"Expected 162 global unique pairs, got {len(global_pairs)}")
    ok("Pair uniqueness OK (162/162) and per-expert counts OK")

    # 5) shared anchor identity (same task_uid per clustering across all)
    # We just check (clustering_id -> set(task_uid)) is size 1 across experts
    by_cl = {"A": set(), "B": set(), "C": set()}
    for e, data in assigns.items():
        for t in data.get("tasks", []):
            if t.get("assignment_role") == "anchor":
                by_cl[t.get("clustering_id")].add(t.get("task_uid"))
    for cid, uids in by_cl.items():
        if len(uids) != 1:
            fail(f"Anchor mismatch for clustering {cid}: got {uids}")
    ok("Anchors are shared consistently across all experts")

    ok("OVERALL: PASS")
    print("READY TO DEPLOY FROM MAIN")

if __name__ == "__main__":
    main()
