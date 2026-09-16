# Upgrade Guide

Odoo database changes are applied when the addon is upgraded. Replacing the source files alone is not a complete upgrade.

## Safe upgrade sequence

1. Read the release notes/changelog.
2. Create a database backup and, when applicable, a filestore backup.
3. Deploy/copy the new addon source.
4. Restart the Odoo application/container if required by the deployment method.
5. Upgrade the WATI addon(s).
6. Confirm the Odoo registry loads successfully.
7. Run application/health checks.
8. Test inbound and outbound WhatsApp flows.

## CLI example

Core only:

```bash
odoo -d CUSTOMER_DB -u wati_connector --stop-after-init
```

Core plus installed integrations:

```bash
odoo -d CUSTOMER_DB \
  -u wati_connector,wati_connector_crm,wati_connector_sale,wati_connector_account,wati_connector_project \
  --stop-after-init
```

Only include optional modules that are actually installed in the customer's database.

## Database migrations

Versioned migrations live inside the addon and are executed by Odoo during module upgrades when applicable. Do not manually run migration SQL unless a release explicitly instructs you to do so.

## Docker/container deployments

A production container workflow should perform the same sequence: backup → deploy new image/source → module upgrade → registry/health verification → serve traffic.

## Rollback

If an upgrade fails, stop the deployment and restore the database/filestore backup that matches the previous addon source version. Do not run an older source tree against a partially migrated production database without an approved rollback procedure.
