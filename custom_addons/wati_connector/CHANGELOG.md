# Changelog

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
