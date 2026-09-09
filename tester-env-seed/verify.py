#!/usr/bin/env python3
"""Verify Rybbit seed state: ClickHouse counts + authenticated dashboard endpoints.

Usage: python3 verify.py [--base-url http://172.17.0.1:3001] [--site-id 1]
        [--email tester@example.com] [--password TestPass123!]

Sites are private, so /has-data and /overview need a session cookie: the script
signs in via better-auth (/api/auth/sign-in/email) first. Exit 0 when all pass.
"""
import argparse
import base64
import json
import sys
import urllib.request
import urllib.error


def ch(sql, user="default", password="frog"):
    req = urllib.request.Request("http://127.0.0.1:8123/", data=sql.encode(), headers={
        "Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode().strip()


def api(base, path, cookie=None):
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    try:
        req = urllib.request.Request(base + path, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode() or "null"
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode(errors="replace")


def sign_in(base, email, password):
    req = urllib.request.Request(
        base + "/api/auth/sign-in/email",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        cookies = []
        # urllib headers: get_all_matching_headers or .get_all()
        try:
            for h in r.headers.get_all("Set-Cookie"):
                cookies.append(h.split(";", 1)[0])
        except Exception:
            sc = r.headers.get("Set-Cookie")
            if sc:
                cookies.append(sc.split(";", 1)[0])
        return "; ".join(cookies)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://172.17.0.1:3001")
    ap.add_argument("--email", default="tester@example.com")
    ap.add_argument("--password", default="TestPass123!")
    ap.add_argument("--site-id", type=int, default=1)
    args = ap.parse_args()
    sid = args.site_id
    ok = True
    out = {}

    out["events"] = ch(f"SELECT count() FROM analytics.events WHERE site_id = {sid}")
    out["sessions"] = ch(f"SELECT uniq(session_id) FROM analytics.events WHERE site_id = {sid}")
    out["users"] = ch(f"SELECT uniq(user_id) FROM analytics.events WHERE site_id = {sid}")
    out["bot_events"] = ch(f"SELECT count() FROM analytics.bot_events WHERE site_id = {sid}")
    out["by_page"] = ch(f"SELECT pathname, count() FROM analytics.events WHERE site_id = {sid} GROUP BY pathname ORDER BY pathname FORMAT TabSeparated")
    out["channels"] = ch(f"SELECT channel, count() FROM analytics.events WHERE site_id = {sid} GROUP BY channel ORDER BY channel FORMAT TabSeparated")

    cookie = sign_in(args.base_url, args.email, args.password)
    out["signed_in"] = bool(cookie)

    st, body = api(args.base_url, f"/api/sites/{sid}/has-data", cookie)
    out["has_data"] = {"status": st, "body": body}

    st, body = api(args.base_url, f"/api/sites/{sid}/overview", cookie)
    out["overview"] = {"status": st, "body": body}

    checks = [
        ("events non-zero", out["events"] not in ("0", "")),
        ("sessions non-zero", out["sessions"] not in ("0", "")),
        ("users non-zero", out["users"] not in ("0", "")),
        ("no bot leakage", out["bot_events"] == "0"),
        ("has-data true", out["has_data"]["status"] == 200 and body_true(out["has_data"]["body"])),
        ("overview pageviews > 0", overview_pageviews(out["overview"]) > 0),
    ]
    print(json.dumps(out, indent=2))
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
        ok = ok and passed
    sys.exit(0 if ok else 1)


def body_true(b):
    if b is True:
        return True
    if isinstance(b, dict):
        return b.get("hasData") is True or b.get("has_data") is True or True in b.values()
    return False


def overview_pageviews(o):
    try:
        b = o["body"]
        if isinstance(b, dict):
            for k in ("pageviews", "pageViews"):
                if k in b and isinstance(b[k], (int, float)):
                    return b[k]
            d = b.get("data", b)
            if isinstance(d, dict):
                for k in ("pageviews", "pageViews"):
                    if k in d and isinstance(d[k], (int, float)):
                        return d[k]
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    main()
