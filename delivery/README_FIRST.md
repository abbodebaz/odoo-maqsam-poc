# WATI WhatsApp Connector for Odoo 19

This folder is the customer delivery package for the WATI WhatsApp Connector.

## Package contents

- `wati_connector` — required core addon.
- `wati_connector_crm` — optional CRM integration.
- `wati_connector_sale` — optional Sales integration.
- `wati_connector_account` — optional Accounting integration.
- `wati_connector_project` — optional Project integration.
- `INSTALLATION.md` — first-time installation.
- `CONFIGURATION.md` — WATI API, webhook and permissions setup.
- `UPGRADE.md` — safe upgrade procedure for future releases.
- `TROUBLESHOOTING.md` — common operational checks.

## Compatibility

- Odoo 19.0
- WATI account with API access
- PostgreSQL supported by the target Odoo 19 deployment

## Important

The package does not include credentials, tokens, customer data, database dumps, staging URLs, or environment secrets.

Install the core addon first. Install optional integration addons only when the matching Odoo app is installed.

Current delivery version: `19.0.11.0.3`.
