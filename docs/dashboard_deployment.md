# Dashboard Deployment Notes

## Purpose

This document explains how to build and publish the static PPLayouts dashboard from the current repo state.

## Current structure

Source inputs:
- `dashboard/` — static HTML/CSS/JS pages
- `dashboard-data/` — generated JSON snapshot files

Build output:
- `dashboard-dist/`

## Local build flow

### 1. Export fresh dashboard data

```bash
uv run python scripts/export_dashboard_data.py
```

### 2. Build self-contained static bundle

```bash
uv run python scripts/build_dashboard.py
```

This creates:
- `dashboard-dist/`
  - HTML/CSS/JS dashboard pages
  - `data/*.json` snapshot files

### 3. Preview locally

```bash
cd dashboard-dist
python3 -m http.server 8000
```

Then open:
- `http://127.0.0.1:8000/index.html?bundled=1`

The `bundled=1` query param tells the dashboard to load JSON from `./data/` instead of `../dashboard-data/`.

## Recommended publication model

Preferred options:

### Option A — dedicated dashboard branch

Use a branch that only holds the static dashboard bundle.

Suggested flow:
1. export dashboard data
2. build dashboard bundle
3. copy/publish `dashboard-dist/` contents to dashboard branch
4. point Cloudflare Pages at that branch

Pros:
- avoids noisy generated artifacts on the main working branch
- simple for static hosting

### Option B — separate dashboard repo

Publish `dashboard-dist/` into a separate private repo used only for hosting.

Pros:
- cleanest separation
- keeps the main repo focused on source code

Cons:
- one more repo to maintain

## Cloudflare Pages shape

The dashboard is already compatible with static hosting.

Cloudflare Pages should publish the built static output directory contents.

If using a separate branch/repo, the published root should contain files like:
- `index.html`
- `strategies.html`
- `positions.html`
- `runs.html`
- `experiments.html`
- `styles.css`
- `dashboard.js`
- `data/*.json`

## Access control recommendation

Use Cloudflare Access in front of the site.

Preferred auth provider:
- GitHub

Allowlist:
- Bartek
- Pawel
- Daniel

## Publish workflow script

A publish helper now exists:
- `scripts/publish_dashboard.py`

Basic usage:

```bash
# Export + build + sync bundle into a target checkout/directory
uv run python scripts/publish_dashboard.py ~/path/to/dashboard-publish-repo
```

If the target is a git checkout and you want the script to commit:

```bash
uv run python scripts/publish_dashboard.py ~/path/to/dashboard-publish-repo \
  --commit \
  --message "dashboard: update static bundle"
```

To also push:

```bash
uv run python scripts/publish_dashboard.py ~/path/to/dashboard-publish-repo \
  --commit \
  --push
```

Notes:
- by default the script reruns export + build first
- it mirrors `dashboard-dist/` into the target directory
- it only commits if git reports actual changes

## Recommended next automation step

Use `scripts/publish_dashboard.py` as the basis for a scheduled or manual publish flow that does:
1. `scripts/export_dashboard_data.py`
2. `scripts/build_dashboard.py`
3. sync `dashboard-dist/` into a dashboard branch or separate repo checkout
4. commit only if contents changed
5. push for Cloudflare redeploy

## Important constraint

The dashboard is snapshot-based, not live.

That is acceptable only if:
- data freshness is visible
- export/build failures are surfaced
- viewers do not mistake it for a real-time control surface
