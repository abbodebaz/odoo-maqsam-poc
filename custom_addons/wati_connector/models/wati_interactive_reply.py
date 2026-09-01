from odoo import api, models


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


def _reply_text(value):
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in (
        "title",
        "text",
        "buttonText",
        "displayText",
        "name",
        "description",
        "id",
    ):
        text = _clean(value.get(key))
        if text:
            return text
    return ""


class WatiWebhookEventInteractiveReply(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def ingest(self, payload):
        """Make button/list replies visible as normal inbound conversation text.

        WATI exposes interactive replies in structured webhook keys such as
        `interactiveButtonReply`, `buttonReply` and `listReply`. Depending on the
        WhatsApp/WATI event variant, the top-level `text` can be empty. The core
        inbox stores `text`, so normalize a human-readable label before the
        standard ingestion pipeline runs while preserving the original structured
        reply in raw_payload.
        """
        if not isinstance(payload, dict):
            return super().ingest(payload)

        normalized = dict(payload)
        reply = (
            normalized.get("interactiveButtonReply")
            or normalized.get("buttonReply")
            or normalized.get("listReply")
        )
        label = _reply_text(reply)
        if label and not _clean(normalized.get("text")):
            normalized["text"] = label
        if reply and not _clean(normalized.get("type")):
            normalized["type"] = "interactive"
        return super().ingest(normalized)
