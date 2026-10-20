import json, os, sys, tempfile, unittest
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kw import bot, digest, extractors

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
PROJ = {"site_url": "https://x", "projects": [{"slug": "ros2-nav2", "x": {"enabled": True}}]}
CREDS = {f"X_ROS2_NAV2_{s}": "k" for s in bot.SUFFIXES}


def site_with(posts):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "ros2-nav2"))
    json.dump({"posts": posts}, open(os.path.join(d, "ros2-nav2", "posts.json"), "w"))
    return d


P1 = {"sha": "a" * 40, "short": "aaaaaaa", "date": "2026-10-01T00:00:00Z", "status": "ready", "posts": ["Nav2 update: x 1 → 2"]}
P2 = {**P1, "sha": "b" * 40, "short": "bbbbbbb", "date": "2026-10-02T00:00:00Z", "posts": ["Nav2 update: y 3 → 4", "thread 2"]}


class Bot(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(bot.posting_mode(PROJ["projects"][0], {}), (False, "BOT_POSTING_ENABLED is not 'true'"))
        live, why = bot.posting_mode(PROJ["projects"][0], {"BOT_POSTING_ENABLED": "true"})
        self.assertFalse(live); self.assertIn("X_ROS2_NAV2_API_KEY", why)
        self.assertFalse(bot.posting_mode({"slug": "ros2-nav2", "x": {"enabled": False}}, {"BOT_POSTING_ENABLED": "true", **CREDS})[0])

    def test_dry_run_never_posts(self):
        calls = []
        rep = bot.run(PROJ, site_with([P1]), {}, {}, NOW, post_fn=lambda *a: calls.append(a))
        self.assertEqual(calls, []); self.assertEqual(rep[0]["would_post_next"], P1["posts"])

    def test_live_baseline_then_post_thread(self):
        calls, state = [], {}
        env = {"BOT_POSTING_ENABLED": "true", **CREDS}
        fake = lambda t, c, r: calls.append((t, r)) or str(len(calls))
        bot.run(PROJ, site_with([P1]), state, env, NOW, post_fn=fake)
        self.assertEqual(calls, [])  # first live run: baseline only
        bot.run(PROJ, site_with([P1, P2]), state, env, NOW, post_fn=fake)
        self.assertEqual(calls, [("Nav2 update: y 3 → 4", None), ("thread 2", "1")])
        self.assertEqual(state["ros2-nav2"]["b" * 40]["status"], "posted")

    def test_oauth_header_shape(self):
        h = bot.oauth1_header("POST", bot.TWEET_ENDPOINT, "ck", "cs", "t", "ts", nonce="n", timestamp="1")
        self.assertTrue(h.startswith("OAuth ") and "oauth_signature=" in h)


class Digest(unittest.TestCase):
    def test_render(self):
        ch = [{"commit": "c" * 40, "date": "2026-10-19T00:00:00Z", "commit_url": "https://g/c", "commit_message": "Tune radius (#5)",
               "pr_number": 5, "pr_url": "https://g/pull/5", "name": "inflation_radius", "old": "0.55", "new": "0.7", "pct_change": 0.2727, "file": "p.yaml"}]
        subj, h, t = digest.render("Nav2", "ros2-nav2", "https://x", ch, NOW, NOW)
        self.assertIn("1 default change", subj)
        self.assertIn("inflation_radius: 0.55 -> 0.7 (+27%)", t)
        self.assertIn("PR #5", h)

    def test_sending_off(self):
        self.assertIsNone(digest.sending_mode({})[0])
        self.assertIsNone(digest.sending_mode({"DIGEST_SENDING_ENABLED": "true", "DIGEST_PROVIDER": "buttondown"})[0])
        self.assertEqual(digest.sending_mode({"DIGEST_SENDING_ENABLED": "true", "DIGEST_PROVIDER": "buttondown", "BUTTONDOWN_API_KEY": "k"})[0], "buttondown")


class Extractors(unittest.TestCase):
    def test_go(self):
        src = "func SetDefaults_Deployment(obj *X) {\n\tobj.Spec.Replicas = ptr.To[int32](1)\n}\nconst DefaultSyncPeriod = 60 * time.Second\n"
        self.assertEqual({k: v["value"] for k, v in extractors.go_defaults("d.go", src).items()},
                         {"Deployment.Spec.Replicas": "1", "DefaultSyncPeriod": "60 * time.Second"})

    def test_module_vars(self):
        src = "debug = False\ncache_size_limit: int = 8\nclass triton:\n    cudagraphs = True\nx = Config(default=3)\n"
        self.assertEqual({k: v["value"] for k, v in extractors.python_module_vars("config.py", src).items()},
                         {"debug": "False", "cache_size_limit": "8", "triton.cudagraphs": "True", "x": "3"})


if __name__ == "__main__":
    unittest.main()
