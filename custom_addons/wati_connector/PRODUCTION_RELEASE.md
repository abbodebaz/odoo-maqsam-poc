# WATI Connector — Production Release Boundary

This addon is the production deliverable for Bayt Alebaa.

## Production package
- Ship: `custom_addons/wati_connector`
- Do not ship: `custom_addons/bayt_alebaa_simulator`

## Release rules
- QA/demo records and Bayt Alebaa simulator models must stay outside `wati_connector`.
- Internal OTP audit/reveal capabilities are development diagnostics and must not be exposed to normal production users.
- Provider/API secrets must remain in Odoo configuration, never source code.
- Template, Automation, OTP, Inbox, Monitor, Smart Buttons, Timeline, Webhook and Settings features belong to the production connector.
- Before customer delivery: install/upgrade on a clean Odoo 19 database, verify access rights, verify menus, and run smoke tests without the simulator addon.

## Delivery principle
The UI demonstrated to the customer should be the same production `wati_connector` addon that is delivered. The simulator is an independent QA dependency only for the development environment.
