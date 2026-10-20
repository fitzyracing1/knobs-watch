"""Weekly digest per project (HTML + text) from knoblog's changes.json.

  python -m kw.digest [--site site] [--days 7] [--send]

Writes site/digest/<slug>/latest.{html,txt} plus a dated copy, and site/digest/index.html with signup options.
Sending is DISABLED until a provider is chosen: --send does nothing unless DIGEST_SENDING_ENABLED == "true" and
DIGEST_PROVIDER is set to a supported provider with its key:
  buttondown : BUTTONDOWN_API_KEY  (creates an email in Buttondown, which mails its own subscriber list; tag per project)
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from .build import ROOT, load_projects

REPO = "fitzyracing1/knobs-watch"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def week_changes(site: str, slug: str, now: datetime, days: int) -> tuple[dict, list[dict]]:
    path = os.path.join(site, slug, "changes.json")
    if not os.path.exists(path):
        return {}, []
    doc = json.load(open(path, encoding="utf-8"))
    cut = now - timedelta(days=days)
    return doc, [c for c in doc["changes"] if c["kind"] in ("changed", "moved") and _dt(c["date"]) >= cut]


def render(name: str, slug: str, site_url: str, changes: list[dict], start: datetime, end: datetime) -> tuple[str, str, str]:
    span = f"{start:%b %d} – {end:%b %d, %Y}"
    subject = f"{name} knobs: {len(changes)} default change{'s' if len(changes) != 1 else ''} ({span})"
    by_commit: dict[str, list[dict]] = {}
    for c in changes:
        by_commit.setdefault(c["commit"], []).append(c)
    txt = [subject, "=" * len(subject), ""]
    rows = []
    if not changes:
        txt.append("No default values changed this week.")
    for sha, cs in by_commit.items():
        c0 = cs[0]
        why = c0.get("commit_message") or ""
        pr = f" (PR #{c0['pr_number']}: {c0['pr_url']})" if c0.get("pr_url") else ""
        txt.append(f"* {c0['date'][:10]} {why}{pr}\n  {c0.get('commit_url') or sha}")
        for c in cs:
            pct = f" ({c['pct_change'] * 100:+.0f}%)" if c.get("pct_change") is not None else ""
            txt.append(f"    {c['name']}: {c['old']} -> {c['new']}{pct}   [{c['file']}]")
        txt.append("")
        rows.append(f"<tr><td colspan='3' style='padding-top:14px'><b>{html.escape(why)}</b> · <a href='{html.escape(c0.get('commit_url') or '')}'>{sha[:7]}</a>"
                    + (f" · <a href='{html.escape(c0['pr_url'])}'>PR #{c0['pr_number']}</a>" if c0.get("pr_url") else "") + f" · {c0['date'][:10]}</td></tr>")
        rows += [f"<tr><td><code>{html.escape(c['name'])}</code></td><td><code>{html.escape(str(c['old']))}</code> → <code>{html.escape(str(c['new']))}</code></td>"
                 f"<td style='color:#666'>{html.escape(c['file'])}</td></tr>" for c in cs]
    txt += [f"Full history: {site_url}/{slug}/", f"Unsubscribe / manage: https://github.com/{REPO}#weekly-digest", ""]
    body = (f"<!doctype html><html><body style='font-family:system-ui,sans-serif;max-width:720px;margin:auto;color:#222'>"
            f"<h2>{html.escape(subject)}</h2>" + ("<p>No default values changed this week.</p>" if not changes else
            "<table style='border-collapse:collapse;width:100%;font-size:14px'>" + "".join(rows) + "</table>")
            + f"<p><a href='{site_url}/{slug}/'>Full {html.escape(name)} knob history</a> · "
            f"<a href='https://github.com/{REPO}#weekly-digest'>manage subscription</a></p></body></html>")
    return subject, body, "\n".join(txt)


def send_buttondown(subject: str, body_html: str, slug: str, key: str) -> str:
    req = urllib.request.Request("https://api.buttondown.com/v1/emails", method="POST",
                                 data=json.dumps({"subject": subject, "body": body_html, "status": "about_to_send",
                                                  "filters": {"filters": [{"field": "subscriber.tags", "operator": "contains", "value": slug}],
                                                              "groups": [], "predicate": "and"}}).encode(),
                                 headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("id", "")


def sending_mode(env: dict) -> tuple[str | None, str]:
    if (env.get("DIGEST_SENDING_ENABLED") or "").strip() != "true":
        return None, "DIGEST_SENDING_ENABLED is not 'true'"
    prov = (env.get("DIGEST_PROVIDER") or "").strip()
    if prov == "buttondown" and env.get("BUTTONDOWN_API_KEY"):
        return prov, "enabled"
    return None, f"provider {prov or '(unset)'} not configured"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--site", default=os.path.join(ROOT, "site"))
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--send", action="store_true")
    a = p.parse_args(argv)
    proj = load_projects()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=a.days)
    prov, why = sending_mode(dict(os.environ)) if a.send else (None, "--send not given")
    cards = []
    for pr in proj["projects"]:
        slug = pr["slug"]
        doc, ch = week_changes(a.site, slug, now, a.days)
        if not doc:
            continue
        cfgname = pr.get("name") or slug
        name = json.load(open(os.path.join(a.site, slug, "feed.json"))).get("title", cfgname) if os.path.exists(os.path.join(a.site, slug, "feed.json")) else cfgname
        name = name.split(" ")[0] if name else slug
        subject, body, txt = render(name, slug, proj["site_url"], ch, start, now)
        d = os.path.join(a.site, "digest", slug)
        os.makedirs(d, exist_ok=True)
        for stem in ("latest", now.strftime("%Y-%m-%d")):
            open(os.path.join(d, f"{stem}.html"), "w", encoding="utf-8").write(body)
            open(os.path.join(d, f"{stem}.txt"), "w", encoding="utf-8").write(txt)
        cards.append(f"<tr><td><b>{html.escape(slug)}</b></td><td>{len(ch)}</td><td><a href='{slug}/latest.html'>HTML</a> · <a href='{slug}/latest.txt'>text</a></td></tr>")
        if prov == "buttondown":
            print(f"[{slug}] sent via buttondown: {send_buttondown(subject, body, slug, os.environ['BUTTONDOWN_API_KEY'])}", file=sys.stderr)
        else:
            print(f"[{slug}] digest written ({len(ch)} changes); not sent: {why}", file=sys.stderr)
    body = (f"<p>Weekly digest of changed defaults per project ({start:%b %d} – {now:%b %d, %Y}). Sending is off until an email provider is chosen.</p>"
            "<table><tr><th>Project</th><th>Changes this week</th><th>Digest</th></tr>" + "".join(cards) + "</table>"
            "<h2>Sign up</h2><ul>"
            f"<li><b>Email:</b> <a href='https://github.com/{REPO}/issues/new?template=digest-signup.yml'>open a signup issue</a> naming the projects you want. "
            "Don't put your email address in the public issue; you'll get a private confirmation link once the email provider is live.</li>"
            f"<li><b>GitHub notifications (works today):</b> watch <a href='https://github.com/{REPO}'>{REPO}</a> → Custom → Releases. "
            "Each weekly refresh can publish a release carrying the digest.</li>"
            "<li><b>Feeds (work today):</b> every project has an Atom feed: <code>/&lt;project&gt;/feed.xml</code>.</li></ul>")
    from .bot import PAGE
    os.makedirs(os.path.join(a.site, "digest"), exist_ok=True)
    open(os.path.join(a.site, "digest", "index.html"), "w", encoding="utf-8").write(PAGE.format(title="knobs-watch weekly digest", body=body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
