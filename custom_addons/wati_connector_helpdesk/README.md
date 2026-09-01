# WATI Connector - Odoo Helpdesk

Optional integration layer for Odoo Enterprise Helpdesk.

## Requirements

- Odoo 19
- `wati_connector`
- Odoo Enterprise `helpdesk`

## Features

- WhatsApp smart button and tab on `helpdesk.ticket`
- Reuses the customer's existing WATI conversation instead of creating duplicates
- Multiple Helpdesk tickets can link to the same WhatsApp conversation
- Displays message count, latest WhatsApp activity and latest delivery status
- Opens the WATI inbox directly on the correct customer conversation
- Stage automations remain fully no-code through the main WATI Automation Builder using:
  - Model: `helpdesk.ticket`
  - Trigger field: `stage_id`

No Helpdesk stage name or WATI template is hardcoded in this addon.

## Installation

Install the main `wati_connector` first, install Odoo Helpdesk, then install this addon from Apps.
