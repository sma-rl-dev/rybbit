# Rybbit tester-env seed (tester-env-seed/ in the fork root)

Seed entry points are the `./tester-env seed` / `./tester-env verify` CLI
commands; this directory holds the scripts they call.

## Credentials (deterministic)
- User: `tester@example.com` / `TestPass123!` (first user → admin via better-auth hook)
- Org: `Test Org` (slug `test-org`)
- Sites: `example.com` (site_id 1, seeded with analytics), `second.com` (site_id 2, empty edge case)

## Seed method
`seed.py` replays a fixed synthetic traffic plan through the public tracking API
`POST /api/track` with browser-like headers (Accept, Accept-Language,
Accept-Encoding, Sec-Fetch-Site/Mode, real Chrome/Firefox/Safari/Edge UAs).
Direct ClickHouse inserts were avoided so channel/browser/session derivation
(`getChannel`, UA parsing, Redis sessions) runs exactly as in production.

Two ingestion gotchas (recorded so fork-integrator keeps them):
1. Bot heuristics: bare curl/python requests are classified as bots
   (`header_heuristics`, missing Accept-Language/sec-fetch headers) and land in
   `bot_events`, invisible to the dashboard. Browser-like headers fix this.
2. Rate-anomaly rule: >(30 events/10s or 120/60s) per (site,ip,ua) tuple diverts
   to `bot_events`. Seed paces at ~0.8 req/s (1.2s sleep). All seed traffic
   shares one egress IP, so bursts are unsafe.

## Dataset (site_id 1, `--days 14` default)
- 8 fixed visitors (`seed-alice-001` … `seed-henry-008`), 4 browsers, 4 langs,
  referrers: direct / google / twitter(x) / github / newsletter-UTM email
- 7 pages: `/`, `/pricing`, `/docs`, `/docs/getting-started`, `/blog`,
  `/blog/launch-post`, `/checkout`
- 184 pageviews / 8 sessions / 8 users (stable across reseeds on the same day)
- Channels: Direct 91, Organic Social 36, Organic Search 35, Referral 21, Email 1
- Verified: `GET /api/sites/1/overview` → `{sessions 8, pageviews 184, users 8}`;
  `GET /api/sites/1/has-data` → `{hasData: true}` (auth required; sites private)

## Timestamps
Backend stamps arrival time; seed replays "today-heavy" traffic (all 8 visitors
on day 0–1, 6 on days 2–6, 4 on older days). Counts/structure identical every
run; absolute dates shift with the calendar — assert on totals, not dates.

## Commands
- Seed: `./tester-env seed` (or `python3 tester-env-seed/seed.py --base-url <backend> --site-id 1 [--days 14]`)
- Verify: `./tester-env verify` (or `python3 tester-env-seed/verify.py --base-url <backend> --site-id 1`)
- Analytics reseed: `sh tester-env-seed/reset-and-seed.sh [--days 14]`
- Full reset: `./tester-env reset && ./tester-env deploy` (compose down -v/up -d,
  then browser signup, then reseed — signup is the only manual step)

## Deployment notes
- Baseline: tag v2.8.0 SHA 4a01c7a2bd18ca07cde3501413a339f376967555
- Backend needs `NODE_ENV=development` + `TRUSTED_ORIGINS` (see
  `docker-compose.tester-env.yml`); source carries the `cors.ts` TRUSTED_ORIGINS patch.
- Overrides: `docker-compose.tester-env.yml`, `Caddyfile.tester-env`.
- Client :3002, backend :3001, proxy :8080 (host ports configurable via
  CLIENT_PORT/BACKEND_PORT/PROXY_PORT env).
