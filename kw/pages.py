"""Top-level knobs-watch pages: site/index.html (all projects) and site/kw.css."""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone

from .build import ROOT, load_projects

CSS = """:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--acc:#f0883e;--card:#161b22;--bd:#30363d}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif}main{max-width:980px;margin:auto;padding:36px 18px}
a{color:#58a6ff}code{background:var(--card);padding:1px 4px;border-radius:4px}h1 span{color:var(--acc)}small,.muted,.meta{color:var(--mut)}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--bd);padding:6px;text-align:left;vertical-align:top}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px}.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px}
.card h2{margin:0 0 4px;font-size:1.15rem}pre{white-space:pre-wrap;background:var(--card);padding:10px;border-radius:8px;border:1px solid var(--bd)}.post{margin:14px 0}
"""


def main() -> int:
    proj = load_projects()
    site = os.path.join(ROOT, "site")
    status = {s["slug"]: s for s in json.load(open(os.path.join(site, "build-status.json")))["projects"]} if os.path.exists(os.path.join(site, "build-status.json")) else {}
    cards = []
    for pr in proj["projects"]:
        slug = pr["slug"]
        cpath = os.path.join(site, slug, "changes.json")
        if not os.path.exists(cpath):
            cards.append(f"<div class='card'><h2>{slug}</h2><p class='muted'>Not built yet{': ' + html.escape(status.get(slug, {}).get('error', '')) if status.get(slug, {}).get('error') else ''}</p></div>")
            continue
        doc = json.load(open(cpath, encoding="utf-8"))
        ch = [c for c in doc["changes"] if c["kind"] in ("changed", "moved") and c["old"] is not None]
        title = json.load(open(os.path.join(site, slug, "feed.json"))).get("title", slug)
        latest = "".join(f"<li><code>{html.escape(c['name'][:60])}</code> {html.escape(str(c['old'])[:24])} → {html.escape(str(c['new'])[:24])} "
                         f"<small>{c['date'][:10]}" + (f" · <a href='{html.escape(c['pr_url'])}'>#{c['pr_number']}</a>" if c.get("pr_url") else "") + "</small></li>"
                         for c in ch[:5])
        cards.append(f"<div class='card'><h2><a href='{slug}/'>{html.escape(title)}</a></h2><p class='muted'>{len(ch)} changed defaults · "
                     f"<a href='{doc['repo']}'>{html.escape(doc['repo'].split('github.com/')[-1])}</a> · <a href='{slug}/feed.xml'>Atom</a> · "
                     f"<a href='posts/#{slug}'>X feed</a> · <a href='digest/{slug}/latest.html'>digest</a></p><ul>{latest or '<li class=muted>No changed values in the window.</li>'}</ul></div>")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>knobs-watch: changed defaults in big projects</title><link rel="stylesheet" href="kw.css"></head><body><main>
<h1>knobs-watch<span>.</span></h1>
<p>Default parameters that changed recently in big open-source projects, read straight from their git history by
<a href="https://github.com/fitzyracing1/knoblog">knoblog</a>. Every change links its commit and, where findable, its PR. Refreshed daily. Last build: {now}.</p>
<p><a href="posts/">X feeds (one per project)</a> · <a href="digest/">Weekly digest + signup</a> · <a href="https://fitzyracing1.github.io/knobs/">What is a knob?</a> ·
<a href="https://github.com/fitzyracing1/knobs-watch">source</a></p>
<div class="grid">{''.join(cards)}</div></main></body></html>"""
    open(os.path.join(site, "index.html"), "w", encoding="utf-8").write(page)
    open(os.path.join(site, "kw.css"), "w").write(CSS)
    open(os.path.join(site, ".nojekyll"), "w").write("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
