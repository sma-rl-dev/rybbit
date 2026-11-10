# DEPLOY-SMA — Rybbit

> Source-build and browser-smoke notes for the `rybbit` RL environment.
> Baseline: tag v2.8.0 (`4a01c7a2bd18ca07cde3501413a339f376967555`).

## Quick Start

```bash
./tester-env deploy    # Build backend+client images from source, start stack, wait healthy
./tester-env seed      # Bootstrap user/org/sites when missing + deterministic analytics
./tester-env verify    # Check seeded state via the same-origin API
./tester-env reset     # Clean slate (containers + volumes; images kept)
```

`PORT` selects the single published entry port (same-origin proxy); the CLI
derives `BASE_URL` from `TESTER_ENV_BROWSER_ORIGIN` (else `http://localhost:$PORT`),
so the dashboard, the API and the trusted CORS origin agree for every run.

## Build

Builds from editable source via compose (no prebuilt images):

- `server/Dockerfile` → backend API on `:3001`
- `client/Dockerfile` → dashboard (compose network only, `:3002`)
- `Caddyfile.tester-env` → same-origin proxy published on `$PORT`
  (`/api/*` → backend, everything else → client); the only host port

```bash
docker compose -f docker-compose.yml -f docker-compose.tester-env.yml build
docker compose -f docker-compose.yml -f docker-compose.tester-env.yml up -d
```

Backend, client and the databases publish no host port, so concurrent stacks
cannot collide; seed/verify query ClickHouse through scoped `compose exec`.

## Environment (pinned in `docker-compose.tester-env.yml`)

- `BETTER_AUTH_SECRET=tester-env-rybbit-deterministic-secret-0123456789abcdef`
- `DISABLE_SIGNUP=false` (first-user signup must stay open)
- `CLUSTER_WORKERS=1`
- `DISABLE_TELEMETRY=true`
- `TRUSTED_ORIGINS` is computed by the CLI for this run's origins
  (consumed by the fork's `server/src/lib/cors.ts` patch; upstream only
  trusts `BASE_URL` in production, which breaks split-origin deployments)
- `NODE_ENV=development` (required: `production` forces Secure
  SameSite=None cookies that plain-http browsers reject, breaking sessions)
- `BASE_URL` = this run's browser origin (baked into the client as
  `NEXT_PUBLIC_BACKEND_URL` at build time). Because that value is inlined per
  build, two runs on different ports cannot share one client image: rybbit is
  serial (`supports_parallel_runs=false`) until the client fetches a relative
  `/api` path.
- No fixed network IPAM: Docker allocates the project-scoped default bridge.
- No redis/clickhouse/postgres host ports; services use the compose network

## Credentials

- URL: the proxy origin, `http://localhost:$PORT` (dashboard + API)
- User: `tester@example.com` / `TestPass123!` (first user → admin)
- Org: `Test Org` (slug `test-org`)
- Sites: `example.com` (site_id 1, seeded), `second.com` (site_id 2, empty edge case)

`seed --bootstrap` recreates the signup wizard state (account → org → sites)
through the public auth API when the volume set is fresh, and reuses it when
the credentials already exist.

## Reset

```bash
./tester-env reset
```

`docker compose down -v` removes postgres/clickhouse/redis volumes, so the
next `deploy` re-applies migrations from scratch. `seed` bootstraps the
relational baseline again.

## Deterministic Seed

`tester-env-seed/seed.py` replays a fixed synthetic traffic plan through the
public tracking API `POST /api/track` with browser-like headers (Accept,
Accept-Language, sec-fetch, real Chrome/Firefox/Safari/Edge UAs). Direct
ClickHouse inserts are avoided so channel/browser/session derivation runs as
in production.

Two ingestion gotchas:

1. Bot heuristics: bare curl/python requests land in `bot_events`, invisible
   to the dashboard. Browser-like headers fix this.
2. Rate-anomaly rule: >(30 events/10s or 120/60s) per (site,ip,ua) tuple
   diverts to `bot_events`. Seed paces at ~0.8 req/s (1.2s sleep); all seed
   traffic shares one egress IP, so bursts are unsafe.

Dataset (site_id 1, `--days 14` default):

- 8 fixed visitors, 7 pages (`/`, `/pricing`, `/docs`,
  `/docs/getting-started`, `/blog`, `/blog/launch-post`, `/checkout`)
- 184 pageviews / 8 sessions / 8 users (stable across reseeds)
- Channels: Direct 91, Organic Social 36, Organic Search 35, Referral 21, Email 1
- `GET /api/sites/1/overview` → pageviews 184, sessions 8, users 8;
  `GET /api/sites/1/has-data` → `{hasData: true}` (auth required)

Timestamps are arrival-stamped ("today-heavy" replay); assert on
totals, not absolute dates. See `tester-env-seed/SEED-README.md` and
`tester-env-seed/seed.manifest.json`.

## Smoke Test

1. Open `http://localhost:3002`
2. Sign up as `tester@example.com` / `TestPass123!`, workspace `Test Org`
3. Add site `example.com`, then a second site `second.com`
4. Verify the dashboard loads with the seeded 8/8/184 cards and exact
   per-page counts; verify site 2 shows the empty state
5. `compose down -v` + `up -d` re-applies migrations and returns healthy

## Source Patch (on this branch)

- `server/src/lib/cors.ts`: `getTrustedCorsOrigins()` also trusts
  comma-separated `TRUSTED_ORIGINS` env (additive). Required for any
  split-origin deployment.

## Mutation Smoke Test

To confirm the app rebuilds from source and reflects code changes in the UI:

1. Edit a client string, e.g. the login heading, and rebuild:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tester-env.yml up --build -d
   ```
2. Verify the change is visible on the login page, then revert and rebuild.
