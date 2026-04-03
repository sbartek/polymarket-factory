# CR-20260403-016 — Storage monitoring and raw snapshot retention policy

**Date:** 2026-04-03
**Type:** operations / dashboard
**Status:** done

## What changed

- Added `storage.json` export in `scripts/export_dashboard_data.py`
- Added a Storage panel to `dashboard/index.html`
- Added storage formatting support in `dashboard/dashboard.js`
- Added storage chart styling in `dashboard/styles.css`
- Defined raw snapshot retention policy as 730 days
- Added project-storage alerting near the 100 GB limit

## Policy

- Raw market snapshots: retain for 2 years
- Project storage soft alert: 90 GB
- Project storage hard limit reference: 100 GB

## Why

The repo now stores raw market snapshots for future reconstruction, so storage growth needs to be visible before it becomes a problem.
The dashboard can now show both current footprint and recent raw snapshot payload sizes.

## What was NOT changed

- No cleanup job was added yet
- No compression path was added yet
- No automatic pruning runs today

## Signal to watch

- If raw snapshot growth remains low, the 2-year policy is fine
- If the dashboard starts warning near 90 GB, add pruning or compression before hitting 100 GB
