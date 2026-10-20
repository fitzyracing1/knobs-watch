"""Indexable outputs built from knoblog's real changes.json files (no invented data):
/knobs.json, /<project>/knobs.json, /feed.xml (Atom, combined; per-project Atom stays knoblog's /<project>/feed.xml),
/knobs/<project>/<slug>/index.html, /knobs/index.html, /sitemap.xml, /robots.txt."""
from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xesc

from .build import ROOT, load_projects

KINDS = ("changed", "moved")


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:80] or "knob"


def knob_record(slug: str, title: str, repo: str, c: dict, base: str) -> dict:
    kid = f"{slugify(c['name'])}-{c['short']}"
    return {
        "id": f"{slug}/{kid}", "slug": kid, "project": slug, "project_title": title, "repo": repo,
        "knob": c["name"], "path": c.get("file"), "kind": c["kind"], "type": c.get("type"),
        "old_value": c.get("old"), "new_value": c.get("new"),
        "from_version": f"{c['short']}^", "to_version": c["short"],  # knoblog tracks commits, not release tags
        "date": c["date"], "commit": c["commit"], "commit_url": c.get("commit_url"), "file_url": c.get("file_url"),
        "pr_number": c.get("pr_number"), "pr_url": c.get("pr_url"), "commit_message": c.get("commit_message"),
        "pct_change": c.get("pct_change"), "url": f"{base}/knobs/{slug}/{kid}/",
    }


def collect(site: str, proj: dict) -> list[dict]:
    base = proj["site_url"].rstrip("/")
    out = []
    for pr in proj["projects"]:
        slug = pr["slug"]
        p = os.path.join(site, slug, "changes.json")
        if not os.path.exists(p):
            continue
        doc = json.load(open(p, encoding="utf-8"))
        fj = os.path.join(site, slug, "feed.json")
        title = json.load(open(fj)).get("title", slug) if os.path.exists(fj) else slug
        seen = set()
        for c in doc["changes"]:
            if c["kind"] not in KINDS or c.get("old") is None:
                continue
            r = knob_record(slug, title, doc["repo"], c, base)
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append(r)
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def short(v, n=40):
    s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def explain(r: dict) -> tuple[str, str]:
    old, new = r["old_value"], r["new_value"]
    what = (f"In {r['project_title']}, the default of <code>{html.escape(r['knob'])}</code> (defined in "
            f"<code>{html.escape(r['path'] or '?')}</code>) changed from <code>{html.escape(str(old))}</code> to "
            f"<code>{html.escape(str(new))}</code> in commit <code>{r['to_version']}</code> on {r['date'][:10]}.")
    if r.get("pct_change") is not None:
        what += f" That is a {r['pct_change']:+.0f}% change."
    if r.get("commit_message"):
        what += f" The commit message says: “{html.escape(r['commit_message'].splitlines()[0])}”."
    note = (f"If you rely on the old behaviour, set <code>{html.escape(r['knob'])}</code> explicitly to "
            f"<code>{html.escape(str(old))}</code> before upgrading past <code>{r['to_version']}</code>. "
            f"If you never set it, you will get <code>{html.escape(str(new))}</code> after upgrading; read the linked "
            f"commit{' and PR' if r.get('pr_url') else ''} to see why it changed.")
    return what, note


def head(title, desc, canon, depth, extra=""):
    css = "../" * depth + "kw.css"
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><meta name='description' content='{html.escape(desc)}'>"
            f"<link rel='canonical' href='{canon}'><link rel='alternate' type='application/atom+xml' href='{'../' * depth}feed.xml'>"
            f"<link rel='stylesheet' href='{css}'>{extra}</head><body><main>")


def knob_page(r: dict, base: str) -> str:
    title = f"{r['project_title']} {r['knob']}: {short(r['old_value'])} → {short(r['new_value'])} in {r['to_version']}"
    desc = f"{r['project_title']} changed the default of {r['knob']} from {short(r['old_value'], 60)} to {short(r['new_value'], 60)} in commit {r['to_version']} ({r['date'][:10]}). What changed and how to upgrade."
    what, note = explain(r)
    ld = {"@context": "https://schema.org", "@type": "TechArticle", "headline": title[:110], "description": desc,
          "datePublished": r["date"], "dateModified": r["date"], "url": r["url"], "mainEntityOfPage": r["url"],
          "about": r["knob"], "isBasedOn": r["pr_url"] or r["commit_url"],
          "author": {"@type": "Organization", "name": "knobs-watch"}, "publisher": {"@type": "Organization", "name": "knobs-watch"}}
    ldj = json.dumps(ld).replace("</", "<\\/")
    links = [f"<li><a href='{html.escape(r['commit_url'])}'>Commit {r['to_version']}</a></li>"]
    if r.get("pr_url"):
        links.append(f"<li><a href='{html.escape(r['pr_url'])}'>PR #{r['pr_number']}</a></li>")
    if r.get("file_url"):
        links.append(f"<li><a href='{html.escape(r['file_url'])}'>{html.escape(r['path'])} at {r['to_version']}</a></li>")
    return (head(title, desc, r["url"], 3, f"<script type='application/ld+json'>{ldj}</script>")
            + f"<p class='meta'><a href='../../../'>knobs-watch</a> › <a href='../../'>all knobs</a> › <a href='../'>{html.escape(r['project_title'])}</a></p>"
            f"<h1>{html.escape(title)}</h1><table><tr><th>Project</th><td><a href='{html.escape(r['repo'])}'>{html.escape(r['repo'].split('github.com/')[-1])}</a></td></tr>"
            f"<tr><th>Knob</th><td><code>{html.escape(r['knob'])}</code></td></tr><tr><th>File</th><td><code>{html.escape(r['path'] or '')}</code></td></tr>"
            f"<tr><th>Old default</th><td><code>{html.escape(str(r['old_value']))}</code></td></tr><tr><th>New default</th><td><code>{html.escape(str(r['new_value']))}</code></td></tr>"
            f"<tr><th>Version</th><td>{r['from_version']} → {r['to_version']} (commit)</td></tr><tr><th>Date</th><td>{r['date'][:10]}</td></tr></table>"
            f"<h2>What changed</h2><p>{what}</p><h2>Upgrade note</h2><p>{note}</p><h2>Sources</h2><ul>{''.join(links)}</ul>"
            f"<p><a href='../'>More {html.escape(r['project_title'])} knobs</a> · <a href='../../'>All knobs</a> · <a href='../../../{r['project']}/'>{html.escape(r['project_title'])} changelog</a></p>"
            "</main></body></html>")


def table(rows, prefix):
    tr = "".join(f"<tr><td>{r['date'][:10]}</td><td><a href='{(prefix + r['project'] + '/') if prefix else ''}{r['slug']}/'><code>{html.escape(short(r['knob'], 60))}</code></a></td>"
                 f"<td><code>{html.escape(short(r['old_value'], 30))}</code> → <code>{html.escape(short(r['new_value'], 30))}</code></td><td>{r['project_title'] if prefix else r['to_version']}</td></tr>" for r in rows)
    return f"<table><tr><th>Date</th><th>Knob</th><th>Change</th><th>{'Project' if prefix else 'Commit'}</th></tr>{tr}</table>"


def atom(rows, title, self_url, alt_url, updated):
    es = "".join(f"<entry><title>{xesc(r['project_title'] + ' ' + r['knob'] + ': ' + short(r['old_value']) + ' → ' + short(r['new_value']))}</title>"
                 f"<link rel='alternate' href='{xesc(r['url'])}'/><id>{xesc(r['url'])}</id><updated>{r['date']}</updated>"
                 f"<summary>{xesc(explain(r)[0])}</summary></entry>" for r in rows)
    return (f"<?xml version='1.0' encoding='utf-8'?><feed xmlns='http://www.w3.org/2005/Atom'><title>{xesc(title)}</title>"
            f"<link rel='self' href='{self_url}'/><link rel='alternate' href='{alt_url}'/><id>{self_url}</id><updated>{updated}</updated>"
            f"<author><name>knobs-watch</name></author>{es}</feed>")


def w(path, s):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(s)


def main(site: str | None = None, proj: dict | None = None) -> int:
    proj = proj or load_projects()
    site = site or os.path.join(ROOT, "site")
    base = proj["site_url"].rstrip("/")
    rows = collect(site, proj)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    upd = rows[0]["date"] if rows else now
    meta = {"generated": now, "site": base, "count": len(rows)}
    w(os.path.join(site, "knobs.json"), json.dumps({**meta, "knobs": rows}, indent=1))
    w(os.path.join(site, "feed.xml"), atom(rows[:200], "knobs-watch: changed defaults", f"{base}/feed.xml", f"{base}/knobs/", upd))
    urls = [f"{base}/", f"{base}/knobs/"]
    projs = sorted({r["project"] for r in rows}, key=[p["slug"] for p in proj["projects"]].index)
    for slug in [p["slug"] for p in proj["projects"]]:
        pr = [r for r in rows if r["project"] == slug]
        if not os.path.isdir(os.path.join(site, slug)):
            continue
        w(os.path.join(site, slug, "knobs.json"), json.dumps({**meta, "project": slug, "count": len(pr), "knobs": pr}, indent=1))
        urls.append(f"{base}/{slug}/")
        if not pr:
            continue
        t = pr[0]["project_title"]
        w(os.path.join(site, "knobs", slug, "index.html"), head(f"{t}: changed defaults", f"{len(pr)} default value changes in {t}, each with old/new value, commit and upgrade note.", f"{base}/knobs/{slug}/", 2)
          + f"<p class='meta'><a href='../../'>knobs-watch</a> › <a href='../'>all knobs</a></p><h1>{html.escape(t)}: changed defaults</h1>"
          f"<p><a href='../../{slug}/knobs.json'>knobs.json</a> · <a href='../../{slug}/feed.xml'>Atom</a></p>{table(pr, '')}</main></body></html>")
        urls.append(f"{base}/knobs/{slug}/")
        for r in pr:
            w(os.path.join(site, "knobs", slug, r["slug"], "index.html"), knob_page(r, base))
            urls.append(r["url"])
    w(os.path.join(site, "knobs", "index.html"),
      head("All changed defaults · knobs-watch", f"{len(rows)} default value changes across {len(projs)} open-source projects, one page each.", f"{base}/knobs/", 1)
      + f"<p class='meta'><a href='../'>knobs-watch</a></p><h1>All changed defaults ({len(rows)})</h1>"
      f"<p>Projects: {' · '.join(f'<a href={chr(39)}{p}/{chr(39)}>{p}</a>' for p in projs)} · <a href='../knobs.json'>knobs.json</a> · <a href='../feed.xml'>Atom</a></p>"
      + table(rows, "./") + "</main></body></html>")
    w(os.path.join(site, "sitemap.xml"), "<?xml version='1.0' encoding='utf-8'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
      + "".join(f"<url><loc>{xesc(u)}</loc></url>" for u in dict.fromkeys(urls)) + "</urlset>")
    w(os.path.join(site, "robots.txt"), f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    print(f"seo: {len(rows)} knob pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
