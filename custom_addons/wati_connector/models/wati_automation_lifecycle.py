import logging
from datetime import timedelta

from odoo import _, api, fields, models

from .wati_automation_guard import (
    _digits,
    _extract_external_message_id,
    _payload_broadcast_name,
    _payload_error_text,
    _payload_template_name,
)


_logger = logging.getLogger(__name__)

_LIFECYCLE_RANK = {
    "accepted": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
}

_FAILED_TOKENS = ("failed", "error", "undelivered", "rejected", "expired")


def _canonical_delivery_state(value):
    """Map the various WATI/WhatsApp webhook labels to our canonical state.

    WATI may send labels such as `templateMessageSent`, `delivered`,
    `messageRead`, or `templateMessageFailed`.  Keep the mapping deliberately
    small and predictable so the automation log behaves as a state machine.
    """
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    if "read" in text:
        return "read"
    if "deliver" in text:
        return "delivered"
    if any(token in text for token in _FAILED_TOKENS):
        return "failed"
    if "sent" in text:
        return "sent"
    return ""


def _normalise_phone(value):
    digits = _digits(value)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) >= 9:
        digits = "966" + digits[1:]
    elif len(digits) == 9 and digits.startswith("5"):
        digits = "966" + digits
    return digits


class WatiAutomationRuleLifecycle(models.Model):
    _inherit = "wati.automation.rule"

    @api.depends("log_ids", "log_ids.status", "log_ids.is_test")
    def _compute_counts(self):
        """Use customer-visible delivery as success, not API acceptance."""
        Log = self.env["wati.automation.log"]
        for rule in self:
            common = [("rule_id", "=", rule.id), ("is_test", "=", False)]
            rule.run_count = Log.search_count(common)
            rule.success_count = Log.search_count(
                common + [("status", "in", ("delivered", "read"))]
            )
            rule.failure_count = Log.search_count(common + [("status", "=", "failed")])
            rule.accepted_count = Log.search_count(
                common + [("status", "in", ("accepted", "sent"))]
            )


class WatiAutomationLogLifecycle(models.Model):
    _inherit = "wati.automation.log"

    status = fields.Selection(
        selection_add=[("read", "تمت القراءة")],
        ondelete={"read": "cascade"},
    )

    accepted_at = fields.Datetime(string="وقت قبول الطلب", readonly=True, index=True)
    sent_at = fields.Datetime(string="وقت الإرسال", readonly=True, index=True)
    delivered_at = fields.Datetime(string="وقت التسليم", readonly=True, index=True)
    read_at = fields.Datetime(string="وقت القراءة", readonly=True, index=True)
    failed_at = fields.Datetime(string="وقت الفشل", readonly=True, index=True)
    last_webhook_at = fields.Datetime(string="آخر Webhook", readonly=True, index=True)
    last_webhook_status = fields.Char(string="آخر حالة Webhook", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        stamp_field = {
            "accepted": "accepted_at",
            "sent": "sent_at",
            "delivered": "delivered_at",
            "read": "read_at",
            "failed": "failed_at",
        }
        prepared = []
        for original in vals_list:
            vals = dict(original)
            field_name = stamp_field.get(vals.get("status"))
            if field_name and not vals.get(field_name):
                vals[field_name] = now
            prepared.append(vals)
        return super().create(prepared)

    def write(self, vals):
        status = vals.get("status")
        stamp_field = {
            "accepted": "accepted_at",
            "sent": "sent_at",
            "delivered": "delivered_at",
            "read": "read_at",
            "failed": "failed_at",
        }.get(status)
        if not stamp_field:
            return super().write(vals)

        result = True
        now = fields.Datetime.now()
        for record in self:
            local_vals = dict(vals)
            if not record[stamp_field] and stamp_field not in local_vals:
                local_vals[stamp_field] = now
            result = super(WatiAutomationLogLifecycle, record).write(local_vals) and result
        return result


class WatiWebhookEventLifecycle(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def _update_automation_delivery(self, payload):
        """Correlate a WATI webhook and advance the automation log monotonically.

        Rules:
        * accepted -> sent -> delivered -> read only moves forward.
        * failed may replace accepted/sent, but never delivered/read.
        * delivered/read are stronger evidence than an earlier failed event and
          may recover that historical row if WATI later proves delivery.
        * out-of-order/duplicate webhooks never downgrade the customer-visible
          state.
        """
        if not isinstance(payload, dict):
            return

        raw_status = str(
            payload.get("statusString")
            or payload.get("status")
            or payload.get("eventType")
            or payload.get("type")
            or ""
        ).strip()
        target_state = _canonical_delivery_state(raw_status)
        if not target_state:
            return

        external_id = str(
            payload.get("whatsappMessageId")
            or payload.get("id")
            or _extract_external_message_id(payload)
            or ""
        ).strip()
        broadcast_name = _payload_broadcast_name(payload)
        template_name = _payload_template_name(payload)
        phone = _normalise_phone(
            payload.get("waId")
            or payload.get("whatsappNumber")
            or payload.get("phoneNumber")
            or ""
        )

        Log = self.env["wati.automation.log"].sudo()
        active_states = ("accepted", "sent", "delivered", "read", "failed")
        log = Log.browse()

        if external_id:
            log = Log.search(
                [
                    ("external_message_id", "=", external_id),
                    ("status", "in", active_states),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
        if not log and broadcast_name:
            log = Log.search(
                [
                    ("broadcast_name", "=", broadcast_name),
                    ("status", "in", active_states),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
        if not log and external_id:
            log = Log.search(
                [
                    ("response_excerpt", "ilike", external_id),
                    ("status", "in", active_states),
                ],
                order="create_date desc, id desc",
                limit=1,
            )
        if not log and phone:
            # Phone fallback is intentionally conservative.  It is used only
            # when exactly one recent candidate exists, avoiding accidental
            # correlation when multiple automations contact the same customer.
            cutoff = fields.Datetime.now() - timedelta(minutes=60)
            domain = [
                ("phone", "=", phone),
                ("status", "in", active_states),
                ("create_date", ">=", cutoff),
            ]
            if template_name:
                domain.append(("template_name", "=", template_name))
            candidates = Log.search(domain, order="create_date desc, id desc", limit=2)
            if len(candidates) == 1:
                log = candidates

        if not log:
            _logger.info(
                "WATI lifecycle webhook could not be correlated: status=%s external_id=%s broadcast=%s phone=%s",
                raw_status,
                external_id,
                broadcast_name,
                phone,
            )
            return

        now = fields.Datetime.now()
        current = log.status
        values = {
            "last_webhook_at": now,
            "last_webhook_status": raw_status[:255],
        }
        if external_id and not log.external_message_id:
            values["external_message_id"] = external_id

        state_changed = False

        if target_state == "failed":
            # Delivery/read is definitive evidence that the customer received
            # the message; never downgrade it because of a late failure event.
            if current not in ("delivered", "read"):
                error_text = _payload_error_text(payload) or (
                    "فشل تسليم الرسالة في WATI/WhatsApp: " + raw_status
                )
                values.update(
                    {
                        "status": "failed",
                        "delivery_status": "failed",
                        "error_message": error_text[:1500],
                    }
                )
                state_changed = current != "failed"
        else:
            target_rank = _LIFECYCLE_RANK[target_state]
            current_rank = _LIFECYCLE_RANK.get(current, -1)

            # A later delivered/read webhook is stronger evidence than an
            # earlier failure and is allowed to recover the row.
            should_advance = (
                current == "failed" and target_state in ("delivered", "read")
            ) or target_rank > current_rank

            if should_advance:
                values.update(
                    {
                        "status": target_state,
                        "delivery_status": target_state,
                        "error_message": False,
                    }
                )
                state_changed = True
            elif current in _LIFECYCLE_RANK:
                # Keep the canonical state aligned with the strongest known
                # lifecycle state even if this webhook arrived out of order.
                values["delivery_status"] = current

        log.write(values)

        if not state_changed:
            return

        if target_state == "failed" and log.rule_id:
            error_text = (values.get("error_message") or "").casefold()
            template_failure = (
                "132001" in error_text
                or "template name does not exist" in error_text
                or ("template" in error_text and "translation" in error_text)
            )
            if template_failure:
                message = (
                    "تم إيقاف الأتمتة تلقائيًا لأن WhatsApp/WATI رفض القالب "
                    f"«{log.template_name}». السبب: {values.get('error_message') or raw_status}"
                )[:1500]
                log.rule_id.with_context(wati_guard_internal=True).write(
                    {
                        "active": False,
                        "template_validation_state": "invalid",
                        "template_validation_message": message,
                        "template_verified_at": fields.Datetime.now(),
                    }
                )
