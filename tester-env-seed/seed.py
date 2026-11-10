#!/usr/bin/env python3
"""Rybbit deterministic seed: realistic analytics via /api/track + one goal + one funnel.

Usage:
  python3 seed.py [--base-url http://localhost:8080] [--site-id 1] [--days 14] [--bootstrap]

Idempotent at the analytics level: clears analytics.events + bot_events for the
target site(s) first, then replays a fixed synthetic traffic plan derived from a
fixed visitor roster (no randomness). Relational seed (user/org/sites) is left
untouched when present; --bootstrap recreates the smoke-test baseline on a
fresh DB via the public signup API (first user -> admin, Test Org, example.com
+ second.com), reusing anything that already exists.

Determinism: fixed visitor roster x fixed per-day page sequences x fixed
timestamps relative to seed day (UTC). Re-running on the same calendar day
produces byte-identical event plans. Across calendar days, timestamps shift
(relative-to-now) but counts and visible dashboard structure stay identical;
scenario assertions should use counts/totals/trends, not absolute dates.

Plus one fixed custom event "Signup $& Bonus" (type custom_event, visitor
seed-alice-001, /pricing) for the special-character Events-table scenario.
It is a non-pageview type, so overview pageviews stay 184 and sessions/users
stay 8/8; total rows become 185.

Requires browser-like headers (Accept, Accept-Language, sec-fetch-site) so the
server-side bot heuristics accept the events as genuine pageviews.
"""
import argparse
import hashlib
import http.cookiejar
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0"
SAFARI_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
EDGE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"

BROWSER_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
}

# Fixed visitor roster: (anonymous_id, ua, language, screen, referrer-profile)
VISITORS = [
    ("seed-alice-001", CHROME_UA, "en-US", (1440, 900), "direct"),
    ("seed-bob-002", FIREFOX_UA, "en-US", (1920, 1080), "google"),
    ("seed-carol-003", SAFARI_UA, "en-US", (1512, 982), "direct"),
    ("seed-dave-004", EDGE_UA, "en-GB", (1366, 768), "twitter"),
    ("seed-erin-005", CHROME_UA, "de-DE", (1536, 864), "direct"),
    ("seed-frank-006", CHROME_UA, "en-US", (1440, 900), "github"),
    ("seed-grace-007", SAFARI_UA, "fr-FR", (1728, 1117), "google"),
    ("seed-henry-008", FIREFOX_UA, "en-US", (1600, 900), "direct"),
]

PAGES = [
    ("/", "Acme Store — Home"),
    ("/pricing", "Acme Store — Pricing"),
    ("/docs", "Acme Store — Docs"),
    ("/docs/getting-started", "Getting Started — Acme Docs"),
    ("/blog", "Acme Blog"),
    ("/blog/launch-post", "Launch Post — Acme Blog"),
    ("/checkout", "Acme Store — Checkout"),
]

REFERRERS = {
    "direct": "",
    "google": "https://www.google.com/",
    "twitter": "https://t.co/",
    "github": "https://github.com/",
}

# Fixed custom event for the special-character display-name scenario. Sent as a
# non-pageview type so overview pageview/sessions/users counts stay identical.
SPECIAL_EVENT_NAME = "Signup $& Bonus"
SPECIAL_EVENT_VISITOR = 0  # seed-alice-001: joins her existing session/user
SPECIAL_EVENT_PATH = "/pricing"


def post(base, path, payload, headers=None, ua=None, timeout=20):
    h = dict(BROWSER_HEADERS)
    if ua:
        h["User-Agent"] = ua
    if headers:
        h.update(headers)
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                 headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500]


def track(base, site_id, visitor, page, title, day_offset, seq, now, extra=None, verbose=False):
    anon, ua, lang, (sw, sh) = visitor[:4]
    # Fixed clock times per sequence index so runs are reproducible.
    clock = [(9, 12), (9, 26), (10, 5), (11, 41), (13, 2), (15, 20), (16, 48), (19, 15)]
    hh, mm = clock[seq % len(clock)]
    # NOTE: timestamps are informational only — the backend stamps arrival time.
    payload = {
        "type": "pageview",
        "site_id": str(site_id),
        "hostname": "example.com" if site_id == 1 else "second.com",
        "pathname": page,
        "page_title": title,
        "language": lang,
        "screenWidth": sw,
        "screenHeight": sh,
        "anonymous_id": anon,
        "referrer": extra.get("referrer", "") if extra else "",
    }
    if extra and extra.get("querystring"):
        payload["querystring"] = extra["querystring"]
    st, body = post(base, "/api/track", payload, ua=ua)
    if verbose and st != 200:
        print("TRACK FAIL", st, body, file=sys.stderr)
    return st == 200


def track_custom_event(base, site_id, visitor, verbose=False):
    """Post the fixed special-character custom event for the Events table."""
    anon, ua, lang, (sw, sh) = visitor[:4]
    payload = {
        "type": "custom_event",
        "site_id": str(site_id),
        "hostname": "example.com" if site_id == 1 else "second.com",
        "pathname": SPECIAL_EVENT_PATH,
        "page_title": "Acme Store — Pricing",
        "language": lang,
        "screenWidth": sw,
        "screenHeight": sh,
        "anonymous_id": anon,
        "referrer": "",
        "event_name": SPECIAL_EVENT_NAME,
        "properties": json.dumps({"plan": "bonus"}),
    }
    st, body = post(base, "/api/track", payload, ua=ua)
    if verbose and st != 200:
        print("TRACK FAIL", st, body, file=sys.stderr)
    return st == 200


def daily_plan(day_idx, days):
    """Deterministic per-day visit plan. Recent days busier than older days."""
    recency = days - day_idx  # 1 = oldest ... days = today
    if recency <= 2:
        return [0, 1, 2, 3, 4, 5, 6, 7]  # all 8 visitors today/yesterday
    if recency <= 7:
        return [0, 1, 2, 3, 4, 5]        # 6 visitors this week
    return [0, 1, 2, 3]                  # 4 visitors older days


def visitor_journey(visitor_idx, day_idx):
    """Fixed page sequence per visitor/day derived from hash (stable, no RNG)."""
    h = int(hashlib.sha256(f"{visitor_idx}/{day_idx}".encode()).hexdigest(), 16)
    depth = 1 + (h % 4)  # 1-4 pageviews per visitor-day
    start = h % len(PAGES)
    seq = []
    for k in range(depth):
        seq.append(PAGES[(start + k) % len(PAGES)])
    # Pricing->checkout funnel walkers: visitors 0 and 5 always pass /pricing then 50% /checkout
    if visitor_idx in (0, 5) and depth >= 2:
        seq[1] = PAGES[1]
        if depth >= 3 and (h % 2 == 0):
            seq[2] = PAGES[6]
    return seq


def build_plan(days):
    plan = []
    for d in range(days):
        for vi in daily_plan(d, days):
            for k, (page, title) in enumerate(visitor_journey(vi, d)):
                ref = REFERRERS[VISITORS[vi][4]]
                extra = {"referrer": ref}
                # One UTM-tagged newsletter visit per week for channel diversity.
                if vi == 4 and d % 7 == 3 and k == 0:
                    extra = {"referrer": "", "querystring": "utm_source=newsletter&utm_medium=email"}
                plan.append((d, vi, k, page, title, extra))
    return plan


def ch_exec(sql):
    # ClickHouse publishes no host port; run scoped queries in its container.
    # RYBBIT_CH_QUERY is exported by the tester-env CLI (compose project run).
    argv = shlex.split(os.environ["RYBBIT_CH_QUERY"]) + [sql]
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=True)
    return out.stdout.strip()


def api(base, opener, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        "Content-Type": "application/json", "Accept": "application/json",
        # Normal browser header: our own configured base origin. The backend
        # (better-auth) rejects origin-less auth POSTs with
        # MISSING_OR_NULL_ORIGIN; this value is exactly the origin the CLI
        # pointed us at, never a foreign origin. No trust expansion.
        "Origin": base})
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, _read_json(r)
    except urllib.error.HTTPError as e:
        return e.code, _read_json(e)


def _read_json(r):
    try:
        return json.loads(r.read().decode() or "null")
    except Exception:
        return None


def bootstrap(base):
    """Create the manifest relational baseline; reuse a complete one as-is.

    Mirrors browser signup: step 1 creates the account (the first user becomes
    admin via the backend hook), step 2 creates the org then the sites
    (client/src/app/signup/page.tsx). Manifest pins: tester@example.com /
    Test Org (test-org) owning example.com (seeded) and second.com (empty).
    A signed-in run already has its baseline, so only a fresh DB signs up.
    Anything in between fails loudly; recovery is the ordinary reset path.
    """
    email = os.environ.get("SEED_EMAIL", "tester@example.com")
    password = os.environ.get("SEED_PASSWORD", "TestPass123!")
    org_name = os.environ.get("SEED_ORG_NAME", "Test Org")
    org_slug = os.environ.get("SEED_ORG_SLUG", "test-org")
    domains = [os.environ.get("SEED_SITE_1_DOMAIN", "example.com"),
               os.environ.get("SEED_SITE_2_DOMAIN", "second.com")]
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    st, _ = api(base, opener, "POST", "/api/auth/sign-in/email", {"email": email, "password": password})
    if st == 200:
        return {"org_id": None, "reused": True}
    st, _ = api(base, opener, "POST", "/api/auth/sign-up/email",
                {"email": email, "name": email.split("@")[0], "password": password})
    if st >= 400:
        raise SystemExit(f"bootstrap sign-up failed (status {st})")
    st, _ = api(base, opener, "POST", "/api/auth/sign-in/email", {"email": email, "password": password})
    if st != 200:
        raise SystemExit("bootstrap sign-in failed after sign-up")
    st, org = api(base, opener, "POST", "/api/auth/organization/create", {"name": org_name, "slug": org_slug})
    if st >= 400:
        raise SystemExit(f"bootstrap organization create failed (status {st})")
    org_id = org["id"]
    st, _ = api(base, opener, "POST", "/api/auth/organization/set-active", {"organizationId": org_id})
    if st >= 400:
        raise SystemExit(f"bootstrap set-active failed (status {st})")
    for domain in domains:
        st, _ = api(base, opener, "POST", f"/api/organizations/{org_id}/sites",
                    {"domain": domain, "name": domain, "type": "web", "public": False,
                     "saltUserIds": False, "blockBots": True})
        if st >= 400:
            raise SystemExit(f"bootstrap addSite {domain} failed (status {st})")
    return {"org_id": org_id, "reused": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--site-id", type=int, default=1)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--bootstrap", action="store_true",
                    help="create first user/org/sites via signup API when missing (idempotent)")
    args = ap.parse_args()

    if args.bootstrap:
        # Relational baseline first: analytics ingestion needs the site.
        bootstrapped = bootstrap(args.base_url)
        print(json.dumps({"bootstrapped": bootstrapped}, indent=2))

    # 0. Clear previous seed analytics for determinism (idempotent reseed).
    before = ch_exec(f"SELECT count() FROM analytics.events WHERE site_id = {args.site_id}")
    ch_exec(f"ALTER TABLE analytics.events DELETE WHERE site_id = {args.site_id}")
    ch_exec(f"ALTER TABLE analytics.bot_events DELETE WHERE site_id = {args.site_id}")
    # ALTER DELETE is async; wait until the mutation applies.
    for _ in range(30):
        time.sleep(2)
        n = ch_exec(f"SELECT count() FROM analytics.events WHERE site_id = {args.site_id}")
        if n == "0":
            break

    now = datetime.now(timezone.utc)
    plan = build_plan(args.days)
    ok = 0
    for (d, vi, k, page, title, extra) in plan:
        if track(args.base_url, args.site_id, VISITORS[vi], page, title,
                 args.days - d, k, now, extra, args.verbose):
            ok += 1
        # Rate-anomaly guard: the tracker's per-(site,ip,ua) tuple rule fires at
        # >30 events/10s and >120/60s; all seed traffic shares one egress IP, so
        # pace well under it. Real visits are also spread across days.
        time.sleep(1.2)

    # 1b. One fixed custom event (non-pageview type: overview pageview counts
    # stay 184). Reuses visitor 0's identity so it joins her existing session
    # and user (sessions/users stay 8/8) and shows in the Events table.
    time.sleep(1.2)
    special_ok = track_custom_event(args.base_url, args.site_id,
                                    VISITORS[SPECIAL_EVENT_VISITOR], args.verbose)

    # 1. Wait for async queue flush (1s interval) then verify.
    time.sleep(6)
    events = ch_exec(f"SELECT count() FROM analytics.events WHERE site_id = {args.site_id}")
    sessions = ch_exec(f"SELECT uniq(session_id) FROM analytics.events WHERE site_id = {args.site_id}")
    users = ch_exec(f"SELECT uniq(user_id) FROM analytics.events WHERE site_id = {args.site_id}")
    by_page = ch_exec(f"SELECT pathname, count() FROM analytics.events WHERE site_id = {args.site_id} AND type = 'pageview' GROUP BY pathname ORDER BY pathname FORMAT TabSeparated")
    pageviews = ch_exec(f"SELECT count() FROM analytics.events WHERE site_id = {args.site_id} AND type = 'pageview'")
    special = ch_exec(f"SELECT count() FROM analytics.events WHERE site_id = {args.site_id} AND type = 'custom_event' AND event_name = '{SPECIAL_EVENT_NAME}'")
    print(json.dumps({
        "site_id": args.site_id,
        "planned": len(plan),
        "accepted": ok,
        "events": events,
        "pageviews": pageviews,
        "sessions": sessions,
        "users": users,
        "by_page": by_page,
        "special_event": SPECIAL_EVENT_NAME,
        "special_event_accepted": special_ok,
        "special_event_rows": special,
        "cleared_before": before,
    }, indent=2))


if __name__ == "__main__":
    main()
