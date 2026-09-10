from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Reclassify historical webhook events with the actionable-alert policy."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["wati.webhook.event"]._repair_webhook_monitor()
