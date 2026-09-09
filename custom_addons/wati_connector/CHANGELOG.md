# Changelog

## 19.0.11.0.1 — Final warning cleanup

- Replaced the removed Odoo 18-era `_sql_constraints` declaration with Odoo 19 `models.Constraint`, restoring the database-level uniqueness guarantee for WATI idempotency keys.
- Added a post-migration verification that fails the upgrade if the idempotency unique constraint is not present.
- Set an explicit migration language to avoid translation-context warnings during historical upgrades.
- Switched the Railway startup locale to `C.UTF-8`, which is available in the Debian-based Odoo image and avoids locale fallback noise.
- Kept the core and optional WATI addon versions aligned.

## 19.0.11.0.0 — Delivery cleanup

- Consolidated historical data corrections into a versioned post-migration instead of running one-off repair XML on every module upgrade.
- Removed the automation-log model `init()` data repair hook.
- Removed unused inbox JavaScript assets left from earlier iterations.
- Renamed development-era runtime modules (`*_fix`, `*_repair`, `*_final`) to stable responsibility-based names.
- Renamed the generic inbox conversation preselection asset so the core connector no longer carries CRM-specific naming.
- Aligned the core and optional WATI addon versions for a coherent delivery bundle.
- Replaced the stale repository README with WATI architecture, deployment, and versioning guidance.
- Strengthened CI with artifact, Ruff, migration-discipline, dependency-boundary, version-alignment, and dead-inbox-asset checks.

## 19.0.10.0.53

- English runtime UI baseline for the WATI connector suite.
