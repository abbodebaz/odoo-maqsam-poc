from odoo import api, models


_TEMPLATE_EVENTS = {
    "templateReviewed",
    "templateQualityUpdated",
    "templateCategoryUpdated",
}


class WatiWebhookEvent(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def ingest(self, payload):
        """Update the template catalog in the same transaction as webhook ingest.

        The generic webhook audit trail remains the source of raw callback history.
        Template lifecycle callbacks additionally update the normalized
        ``wati.template`` record, so users see approval, quality and category
        changes without parsing webhook payloads.
        """
        if isinstance(payload, dict) and payload.get("eventType") in _TEMPLATE_EVENTS:
            self.env["wati.template"].sudo().apply_template_webhook(payload)
        return super().ingest(payload)
