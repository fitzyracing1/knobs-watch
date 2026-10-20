# knobs-watch

**Changed defaults in big open-source projects, refreshed daily.** Site: <https://fitzyracing1.github.io/knobs-watch/>

[knoblog](https://github.com/fitzyracing1/knoblog) runs over a rolling 150-day window of each project's history and
publishes every changed default, with old → new values, the commit message, and the PR link.

| Project | Watched | Site |
|---|---|---|
| PyTorch | `torch/_inductor`, `_dynamo`, `_functorch`, `_export` `config.py` | [/pytorch/](https://fitzyracing1.github.io/knobs-watch/pytorch/) |
| Kubernetes | `SetDefaults_*` in `pkg/apis/**/defaults.go`, kubelet, scheduler, controllers, kubeadm | [/kubernetes/](https://fitzyracing1.github.io/knobs-watch/kubernetes/) |
| Next.js | `defaultConfig` in `config-shared.ts`, image config, shared constants | [/nextjs/](https://fitzyracing1.github.io/knobs-watch/nextjs/) |
| Home Assistant | `homeassistant/const.py`, each integration's `const.py`, `core_config.py` | [/home-assistant/](https://fitzyracing1.github.io/knobs-watch/home-assistant/) |
| PX4 | MC/FW controller `module.yaml` and `*_params.c` | [/px4/](https://fitzyracing1.github.io/knobs-watch/px4/) |
| ROS 2 / Nav2 | `nav2_bringup/params/*.yaml` | [/ros2-nav2/](https://fitzyracing1.github.io/knobs-watch/ros2-nav2/) |
| ArduPilot | `AP_GROUPINFO` tables | [/ardupilot/](https://fitzyracing1.github.io/knobs-watch/ardupilot/) |

Add a project: write `configs/<slug>.yml` (a normal knoblog config) and add it to `projects.yml`.

Beyond knoblog's built-in extractors, `kw/extractors.py` adds:

- `go_defaults`: Kubernetes `SetDefaults_*` assignments and `Default*` constants
- `js_defaults`: nested `defaultConfig = Object.freeze({...})` objects
- `python_module_vars`: torch-style `config.py` module and class attributes
- `python_defaults`: function keyword defaults

## How it runs

`.github/workflows/refresh.yml` runs daily at 06:17 UTC and on manual dispatch:

1. `python -m kw.build`: blob-less shallow clones, cached between runs. Watched blobs are prefetched in one request,
   then each project is built with knoblog into `site/<slug>/`. PR lookups are cached.
2. `python -m kw.bot`: the X feeds (below).
3. `python -m kw.digest`: the weekly digests (below).
4. `python -m kw.pages`: the index page. Then the site deploys to GitHub Pages.

## X bot: one feed per project (posting OFF)

`site/posts/<slug>.json` holds the queue for each project: knoblog `posts.json` entries with `status: ready`, so every
number has already passed knoblog's number gate. Each entry also carries the commit message and PR link. Preview:
<https://fitzyracing1.github.io/knobs-watch/posts/>

This uses the same kill-switch pattern as `fitzyracing1/x-algorithm-changelog`. A project posts **only** when all three hold:

1. the repo variable `BOT_POSTING_ENABLED` is exactly `true`;
2. `projects.yml` has `x: {enabled: true}` for that project;
3. the four secrets `X_<SLUG>_API_KEY`, `X_<SLUG>_API_SECRET`, `X_<SLUG>_ACCESS_TOKEN`, `X_<SLUG>_ACCESS_TOKEN_SECRET`
   are set (`<SLUG>` is upper-cased with `-` → `_`, e.g. `X_ROS2_NAV2_API_KEY`).

Anything else is a dry run, and the log says why. The first live run for a project marks everything as handled
(no backfill). After that it posts at most 1 thread per project per run and 3 per day. State lives in
`data/posted.json`. The workflow passes secrets for `px4` and `ros2-nav2`; copy those env lines for any other project.

## Weekly digest

`site/digest/<slug>/latest.html` and `latest.txt` (plus a dated copy) list the past 7 days of changed defaults, grouped by
commit, with the message and PR link. Index and signup: <https://fitzyracing1.github.io/knobs-watch/digest/>

**Sending is OFF.** On Mondays the workflow calls `kw.digest --send`, which sends nothing unless the repo variable
`DIGEST_SENDING_ENABLED` is `true`, `DIGEST_PROVIDER` is set, and the provider key exists.
`buttondown` is implemented: secret `BUTTONDOWN_API_KEY`, one subscriber tag per project slug.

Signup today: the [signup issue form](https://github.com/fitzyracing1/knobs-watch/issues/new?template=digest-signup.yml)
(it asks for projects only, never email addresses), GitHub release watching, or each project's Atom feed
(`/<slug>/feed.xml`). Once a provider is live, point the digest page's signup link at its hosted form.

## Local

```bash
git clone https://github.com/fitzyracing1/knoblog .knoblog-src
PYTHONPATH=.knoblog-src:. python -m kw.build --only px4,ros2-nav2 && python -m kw.bot && python -m kw.digest && python -m kw.pages
python -m http.server -d site
```

MIT. Part of [knobs](https://github.com/fitzyracing1/knobs).
