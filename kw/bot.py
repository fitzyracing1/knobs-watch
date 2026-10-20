"""Multi-project X bot: knoblog posts.json per project -> one post feed per project -> (optionally) X.

Same safety model as fitzyracing1/x-algorithm-changelog:
  * Live posting for a project only when ALL of these hold, otherwise a dry run:
      - env BOT_POSTING_ENABLED == "true"            (global kill switch, a repo variable)
      - projects.yml `x.enabled: true` for that project
      - its four secrets are set: X_<SLUG>_API_KEY, X_<SLUG>_API_SECRET, X_<SLUG>_ACCESS_TOKEN, X_<SLUG>_ACCESS_TOKEN_SECRET
        (<SLUG> = slug upper-cased, '-' -> '_', e.g. X_ROS2_NAV2_API_KEY)
  * Only knoblog posts with status "ready" are used: every number in them already passed knoblog's number gate.
  * data/posted.json records every handled SHA per project. The first live run for a project marks everything
    as handled and posts nothing (no backfill). At most 1 thread per project per run and 3 per UTC day.

  python -m kw.bot [--site site] [--state data/posted.json]
writes site/posts/<slug>.json (the feed) and site/posts/index.html, and prints the dry-run / live decision per project.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import secrets as _secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .build import ROOT, load_projects

TWEET_ENDPOINT = "https://api.x.com/2/tweets"
SUFFIXES = ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET")
DAILY_CAP = 3


def env_prefix(slug: str) -> str:
    return "X_" + slug.upper().replace("-", "_") + "_"


def posting_mode(project: dict, env: dict) -> tuple[bool, str]:
    if (env.get("BOT_POSTING_ENABLED") or "").strip() != "true":
        return False, "BOT_POSTING_ENABLED is not 'true'"
    if not (project.get("x") or {}).get("enabled"):
        return False, "x.enabled is false in projects.yml"
    missing = [env_prefix(project["slug"]) + s for s in SUFFIXES if not (env.get(env_prefix(project["slug"]) + s) or "").strip()]
    if missing:
        return False, "missing secrets: " + ", ".join(missing)
    return True, "enabled"


def _pct(s: str) -> str:
    return urllib.parse.quote(str(s), safe="-._~")


def oauth1_header(method: str, url: str, ck: str, cs: str, tok: str, ts: str, nonce: str | None = None, timestamp: str | None = None) -> str:
    oauth = {"oauth_consumer_key": ck, "oauth_nonce": nonce or _secrets.token_hex(16), "oauth_signature_method": "HMAC-SHA1",
             "oauth_timestamp": timestamp or str(int(time.time())), "oauth_token": tok, "oauth_version": "1.0"}
    norm = "&".join(f"{k}={v}" for k, v in sorted((_pct(k), _pct(v)) for k, v in oauth.items()))
    base = "&".join(["POST" if method.upper() == "POST" else method.upper(), _pct(url), _pct(norm)])
    oauth["oauth_signature"] = base64.b64encode(hmac.new(f"{_pct(cs)}&{_pct(ts)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


def create_post(text: str, creds: dict, reply_to: str | None = None) -> str:
    body = {"text": text, **({"reply": {"in_reply_to_tweet_id": reply_to}} if reply_to else {})}
    req = urllib.request.Request(TWEET_ENDPOINT, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": oauth1_header("POST", TWEET_ENDPOINT, *(creds[s] for s in SUFFIXES)),
        "Content-Type": "application/json", "User-Agent": "knobs-watch-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return str(json.load(r)["data"]["id"])


def feed_for(project: dict, site: str) -> list[dict]:
    path = os.path.join(site, project["slug"], "posts.json")
    if not os.path.exists(path):
        return []
    posts = json.load(open(path, encoding="utf-8"))["posts"]
    return [p for p in posts if p["status"] == "ready"]


def run(projects: dict, site: str, state: dict, env: dict, now: datetime, post_fn=create_post) -> list[dict]:
    report = []
    day = now.strftime("%Y-%m-%d")
    for pr in projects["projects"]:
        slug, feed = pr["slug"], feed_for(pr, site)
        live, why = posting_mode(pr, env)
        st = state.setdefault(slug, {})
        rec = {"slug": slug, "live": live, "reason": why, "ready": len(feed), "posted": []}
        if live and not st:  # first live run: baseline, no backfill
            for p in feed:
                st[p["sha"]] = {"status": "baseline", "at": now.isoformat()}
            rec["reason"] = f"first live run: marked {len(feed)} existing posts as handled"
        elif live:
            today = sum(1 for v in st.values() if v["status"] == "posted" and v["at"].startswith(day))
            todo = [p for p in sorted(feed, key=lambda p: p["date"]) if p["sha"] not in st]
            if todo and today < DAILY_CAP:
                p = todo[0]
                creds = {s: env[env_prefix(slug) + s] for s in SUFFIXES}
                ids: list[str] = []
                try:
                    for t in p["posts"]:
                        ids.append(post_fn(t, creds, ids[-1] if ids else None))
                    st[p["sha"]] = {"status": "posted", "at": now.isoformat(), "ids": ids}
                except Exception as exc:
                    st[p["sha"]] = {"status": "error", "at": now.isoformat(), "ids": ids, "error": str(exc)[:300]}
                rec["posted"].append(p["sha"])
        else:
            nxt = [p for p in sorted(feed, key=lambda p: p["date"]) if p["sha"] not in st]
            rec["would_post_next"] = nxt[0]["posts"] if nxt else None
        report.append(rec)
    return report


def write_feeds(projects: dict, site: str, report: list[dict]) -> None:
    out = os.path.join(site, "posts")
    os.makedirs(out, exist_ok=True)
    cards = []
    for pr, rec in zip(projects["projects"], report):
        feed = feed_for(pr, site)
        json.dump({"project": pr["slug"], "handle": (pr.get("x") or {}).get("handle") or None, "live": rec["live"],
                   "mode": rec["reason"], "note": "Text only unless live. Every post passed knoblog's number gate.",
                   "posts": sorted(feed, key=lambda p: p["date"], reverse=True)},
                  open(os.path.join(out, f"{pr['slug']}.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        items = "".join(
            f"<div class='post'><div class='meta'>{html.escape(p['date'][:10])} · <a href='{html.escape(p.get('commit_url') or '')}'>{p['short']}</a>"
            + (f" · <a href='{html.escape(p['pr_url'])}'>PR #{p['pr_number']}</a>" if p.get("pr_url") else "") + "</div>"
            + "".join(f"<pre>{html.escape(t)}</pre>" for t in p["posts"]) + "</div>"
            for p in sorted(feed, key=lambda p: p["date"], reverse=True)[:15])
        cards.append(f"<h2 id='{pr['slug']}'>{html.escape(pr['slug'])} <small>({len(feed)} ready · "
                     f"<a href='{pr['slug']}.json'>{pr['slug']}.json</a> · {'LIVE' if rec['live'] else 'dry run: ' + html.escape(rec['reason'])})</small></h2>"
                     + (items or "<p class='muted'>No ready posts in the window.</p>"))
    page = PAGE.format(title="knobs-watch X feeds", body="<p>One feed per project, generated from knoblog's <code>posts.json</code>. "
                       "Posting is off by default (global <code>BOT_POSTING_ENABLED</code>, per-project <code>x.enabled</code> and secrets).</p>" + "".join(cards))
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(page)


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="../kw.css"></head><body><main><p><a href="../">← knobs-watch</a></p><h1>{title}</h1>{body}</main></body></html>"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--site", default=os.path.join(ROOT, "site"))
    p.add_argument("--state", default=os.path.join(ROOT, "data", "posted.json"))
    a = p.parse_args(argv)
    projects = load_projects()
    state = json.load(open(a.state)) if os.path.exists(a.state) else {}
    report = run(projects, a.site, state, dict(os.environ), datetime.now(timezone.utc))
    write_feeds(projects, a.site, report)
    if any(r["live"] for r in report):
        os.makedirs(os.path.dirname(a.state), exist_ok=True)
        json.dump(state, open(a.state, "w"), indent=1, sort_keys=True)
    for r in report:
        print(f"[{r['slug']}] {'LIVE' if r['live'] else 'DRY RUN'} ({r['reason']}); {r['ready']} ready; posted {r['posted']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
