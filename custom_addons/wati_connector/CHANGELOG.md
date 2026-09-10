# Changelog

## 19.0.11.0.4 — Final delivery hardening

- Removed the last mixed-language runtime copy from Template Builder styling and kept the customer-facing source consistently English.
- Moved CRM-specific customer-context logic out of the provider-facing core and into the optional `wati_connector_crm` addon, preserving a clean dependency boundary.
- Runtime-validated installation of the optional CRM addon on the Odoo 19 QA environment after the controller split.
- Made the release ZIP checksum file portable by referencing the archive basename instead of a build-directory path.
- Kept the core and all optional CRM, Sales, Accounting, and Project addons version-aligned for the final bundle.

## 19.0.11.0.3 — Customer delivery QA hardening

- Validated a fresh Odoo 19 installation against a clean PostgreSQL database and confirmed WATI send/receive operation in customer-style QA.
- Improved the user-level WATI account and role settings layout for clearer assignment and security guidance.
- Reworked webhook monitoring so external WATI lifecycle traffic and legacy/v2 duplicates remain audit records instead of inflating actionable integration alerts.
- Added a dedicated `Events to Review` dashboard action for webhook events that genuinely require manual attention.
- Added a versioned webhook-monitor migration to reclassify historical events with the new actionable-alert semantics.
- Hardened workspace QWeb inheritance selectors after the KPI change to avoid OWL template inheritance failures.
- Kept the core and all optional CRM, Sales, Accounting, and Project addons version-aligned.

## 19.0.11.0.2 — Warning-free template metadata

- Disambiguated editable draft header labels from provider-mirrored header fields.
- Removed the final WATI model metadata warnings seen during the Odoo registry upgrade.
- Kept the complete WATI addon bundle version-aligned.

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
