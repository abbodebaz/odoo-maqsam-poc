# Odoo × WATI WhatsApp Connector

Production-oriented WATI integration for Odoo 19. The connector keeps WhatsApp operations inside Odoo while preserving a clean boundary between provider transport, core WhatsApp features, and optional business-app integrations.

## WATI delivery bundle

- `wati_connector` — core application: inbox, conversations/messages, templates, automation, OTP Bridge, smart buttons, customer WhatsApp timeline, webhook monitoring, settings, access control, and WATI API transport.
- `wati_connector_crm` — CRM lead/opportunity integration.
- `wati_connector_sale` — quotations and sales-order integration.
- `wati_connector_account` — customer-invoice integration.
- `wati_connector_project` — project-task integration.

The core module intentionally does not depend on CRM, Sales, Accounting, or Project. Optional Odoo models stay in their dedicated integration modules.

## Architecture

Provider HTTP calls are centralized in `wati_connector/services/`. Controllers remain transport-oriented and delegate business rules to models/services. Persistent correctness, idempotency, message correlation, template lifecycle state, automation logs, and webhook reconciliation are database-backed.

Historical data corrections are versioned in `wati_connector/migrations/`. Production data XML is reserved for persistent configuration such as menus, sequences, access synchronization, and scheduled jobs; one-off repair functions must not run on every module upgrade.

See `custom_addons/wati_connector/ARCHITECTURE.md` for the architectural boundaries and invariants.

## Versioning

WATI modules use Odoo-style five-part versions:

`19.0.<release>.<minor>.<patch>`

The delivery bundle is version-aligned. Release `19.0.11.0.0` is the pre-delivery cleanup baseline.

## Quality gate

`.github/workflows/wati-quality.yml` validates:

- Python syntax and critical Ruff correctness rules.
- XML and manifest integrity.
- English-only runtime source outside `i18n/`.
- No generated/debug artifacts committed to the WATI bundle.
- No one-off repair XML in the production manifest.
- No optional Odoo business-model leakage into the core connector.
- No direct HTTP transport outside the WATI service layer.
- Aligned WATI module versions and clean production model filenames.

## Railway deployment

The Railway entrypoint is `odoo-railway-start.sh`. It waits for PostgreSQL, installs/upgrades the configured WATI module set, clears generated Odoo web assets after an upgrade, and starts Odoo 19.

The module set can be configured with `WATI_MODULES`. The default is `wati_connector`.

## Repository note

`maqsam_connector` is a separate legacy/POC integration and is not part of the WATI delivery bundle or the default WATI deployment path.
