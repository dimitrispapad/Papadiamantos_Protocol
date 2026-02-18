import shutil
from pathlib import Path

SRC_ROOT = Path("papadiamantis-eval-netlify")
SITE = Path("site")

def copytree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

def main():
    if not SRC_ROOT.exists():
        raise SystemExit(f"Missing {SRC_ROOT}. Are you in repo root?")

    # fresh site/
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "assets").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "assignments").mkdir(parents=True, exist_ok=True)

    # copy index + assets
    shutil.copy2(SRC_ROOT / "index.html", SITE / "index.html")
    for p in (SRC_ROOT / "assets").glob("*"):
        if p.is_file():
            shutil.copy2(p, SITE / "assets" / p.name)

    # copy assignment JSONs only
    assign_src = SRC_ROOT / "data" / "assignments"
    for p in assign_src.glob("E*.json"):
        shutil.copy2(p, SITE / "data" / "assignments" / p.name)
    shutil.copy2(assign_src / "manifest.json", SITE / "data" / "assignments" / "manifest.json")

    # add simple 404 page (used by redirects)
    (SITE / "404.html").write_text("<!doctype html><meta charset='utf-8'><title>404</title><h1>404</h1>", encoding="utf-8")

    print("[OK] Built clean site/ directory.")
    print("Contents:")
    for p in sorted(SITE.rglob("*")):
        if p.is_file():
            print(" -", p)

if __name__ == "__main__":
    main()
