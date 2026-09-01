from odoo import api, fields, models

from .wati_models import _clean_text, _payload_message_identity


_MEDIA_PREVIEWS = {
    "image": "📷 صورة",
    "video": "🎥 فيديو",
    "audio": "🎵 ملف صوتي",
    "voice": "🎙️ رسالة صوتية",
    "document": "📎 مستند",
    "sticker": "🪄 ملصق",
}


class WatiWebhookEventMediaHardening(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def ingest(self, payload):
        result = super().ingest(payload)
        try:
            self._update_media_preview(payload)
        except Exception:
            # Media preview enrichment must never make the webhook return a
            # non-200 response. WATI retries webhook failures aggressively, so
            # the core event ingestion remains authoritative.
            pass
        return result

    @api.model
    def _update_media_preview(self, payload):
        if not isinstance(payload, dict):
            return

        message_type = _clean_text(payload.get("type")).casefold()
        placeholder = _MEDIA_PREVIEWS.get(message_type)
        if not placeholder:
            return

        caption = _clean_text(payload.get("text"))
        preview = caption or placeholder
        whatsapp_message_id = _clean_text(payload.get("whatsappMessageId"))
        local_message_id = _clean_text(payload.get("localMessageId"))
        message_identity = _payload_message_identity(payload)

        Message = self.env["wati.message"].sudo()
        message = Message.browse()
        if whatsapp_message_id:
            message = Message.search(
                [("whatsapp_message_id", "=", whatsapp_message_id)],
                order="id desc",
                limit=1,
            )
        if not message and local_message_id:
            message = Message.search(
                [("local_message_id", "=", local_message_id)],
                order="id desc",
                limit=1,
            )
        if not message and message_identity:
            message = Message.search(
                [("name", "=", message_identity)],
                order="id desc",
                limit=1,
            )
        if not message or not message.conversation_id:
            return

        # Keep the actual message text untouched: an empty text is meaningful
        # for a media-only WhatsApp message. Only the conversation preview gets
        # a human-readable media label.
        message.conversation_id.write(
            {
                "last_message": preview,
                "last_message_at": fields.Datetime.now(),
            }
        )
