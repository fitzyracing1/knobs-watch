"""python -m kw.build [--only slug,slug] [--out site]: clone/refresh each project and run knoblog into site/<slug>/."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from knoblog import cli as KC
from knoblog import config as C

from .extractors import register

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_projects(path: str = os.path.join(ROOT, "projects.yml")) -> dict:
    return C.parse_text(open(path, encoding="utf-8").read(), path)


def refresh_clone(url: str, dest: str, branch: str | None, since: str, depth: int | None = None) -> None:
    cut = f"--depth={depth}" if depth else f"--shallow-since={since}"
    if os.path.isdir(dest):
        subprocess.run(["git", "fetch", "-q", "--filter=blob:none", cut, "origin",
                        f"+refs/heads/{branch}:refs/heads/{branch}" if branch else "HEAD"], cwd=dest, check=True)
        if branch:
            subprocess.run(["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"], cwd=dest, check=True)
        else:
            subprocess.run(["git", "update-ref", "HEAD", "FETCH_HEAD"], cwd=dest, check=False)
    else:
        args = ["git", "clone", "-q", "--bare", "--filter=blob:none", cut]
        if branch:
            args += ["--branch", branch]
        subprocess.run(args + [url, dest], check=True)


def prefetch_blobs(dest: str, paths: list[str], since: str) -> int:
    """Fetch all missing blobs for the watched paths in one request instead of one lazy fetch per blob."""
    spec = [f":(glob){p}" for p in paths] if paths and paths != ["**"] else []
    out = subprocess.run(["git", "rev-list", "--objects", "--missing=print", f"--since={since}", "HEAD", "--", *spec],
                         cwd=dest, capture_output=True, text=True).stdout
    oids = sorted({l[1:].split()[0] for l in out.splitlines() if l.startswith("?")})
    # also the parent-side blobs of the oldest commits: include HEAD~ trees reachable within the window (covered above)
    for i in range(0, len(oids), 2000):
        subprocess.run(["git", "-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "origin", "--no-tags", "--no-write-fetch-head",
                        "--filter=blob:none", "--stdin"], cwd=dest, input="\n".join(oids[i:i + 2000]) + "\n", text=True, check=False)
    return len(oids)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(ROOT, "site"))
    p.add_argument("--cache", default=os.path.join(ROOT, ".cache"))
    p.add_argument("--only", default="")
    a = p.parse_args(argv)
    register()
    proj = load_projects()
    since = (datetime.now(timezone.utc) - timedelta(days=int(proj.get("window_days") or 150))).strftime("%Y-%m-%d")
    only = {s for s in a.only.split(",") if s}
    status = []
    for pr in proj["projects"]:
        slug = pr["slug"]
        if only and slug not in only:
            continue
        cfgpath = os.path.join(ROOT, pr["config"])
        cfg = C.load(cfgpath)
        dest = os.path.join(a.cache, slug + ".git")
        print(f"[{slug}] refresh {cfg['repo']} since {since}", file=sys.stderr, flush=True)
        try:
            refresh_clone(cfg["repo"], dest, cfg.get("branch"), since, pr.get("clone_depth"))
            subprocess.run(["git", "remote", "set-url", "origin", cfg["repo"]], cwd=dest, check=False)
            n = prefetch_blobs(dest, cfg["watch"]["paths"], since)
            print(f"[{slug}] prefetched {n} blobs", file=sys.stderr, flush=True)
            # bare clone: knoblog reads HEAD; branch handled by refresh_clone, so drop it from the run.
            KC.main(["run", "--repo", dest, "--config", cfgpath, "--out", os.path.join(a.out, slug), "--no-fetch", "--no-llm",
                     "--since", since, "--site-url", f"{proj['site_url']}/{slug}/", "--cache-dir", a.cache, "--pr-lookup"])
            status.append({"slug": slug, "ok": True})
        except (Exception, SystemExit) as exc:  # one broken project must not take the others down
            print(f"[{slug}] FAILED: {exc}", file=sys.stderr)
            status.append({"slug": slug, "ok": False, "error": str(exc)})
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "build-status.json"), "w") as f:
        json.dump({"since": since, "projects": status}, f, indent=1)
    return 0 if any(s["ok"] for s in status) else 1


if __name__ == "__main__":
    raise SystemExit(main())
