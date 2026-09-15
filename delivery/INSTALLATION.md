# Installation Guide

## 1. Back up Odoo

Before installing third-party code, create a database backup and, if applicable, a filestore backup.

## 2. Copy the addons

Copy the contents of the package `addons/` directory into a directory that is included in Odoo's `addons_path`.

Example:

```text
/opt/odoo/custom_addons/
  wati_connector/
  wati_connector_crm/
  wati_connector_sale/
  wati_connector_account/
  wati_connector_project/
```

The exact path depends on the customer's Odoo deployment.

## 3. Restart Odoo and update the Apps list

Restart Odoo after copying the addon source, then enable Developer Mode and run **Apps → Update Apps List**.

## 4. Install the core addon

Install **WATI WhatsApp Connector** (`wati_connector`).

Core dependencies are declared in the addon manifest and include Odoo base/web/contacts/base automation components.

## 5. Install optional integrations

Install only the integrations needed by the customer:

- `wati_connector_crm` requires Odoo CRM (`crm`).
- `wati_connector_sale` requires Sales (`sale_management`).
- `wati_connector_account` requires Accounting/Invoicing (`account`).
- `wati_connector_project` requires Project (`project`).

## 6. Configure WATI

Open the WATI app in Odoo and complete the connection, webhook and access settings described in `CONFIGURATION.md`.

## CLI installation example

Use the customer's normal Odoo executable/configuration and database name. Example:

```bash
odoo -d CUSTOMER_DB -i wati_connector --stop-after-init
```

Optional integrations can be installed separately after their Odoo dependencies are available.

## Post-install verification

Verify all of the following before handover:

1. Odoo starts with no WATI registry errors.
2. WATI Settings opens successfully.
3. Connection test succeeds.
4. The webhook endpoint is configured in WATI.
5. A test inbound message reaches Odoo.
6. A permitted user can open the Inbox.
7. A test outbound session/template message succeeds.
