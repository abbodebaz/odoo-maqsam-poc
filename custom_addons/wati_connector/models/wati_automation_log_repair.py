import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


class WatiAutomationLogRepair(models.Model):
    _inherit = "wati.automation.log"

    ui_state = fields.Selection(
        [
            ("accepted", "تم قبول الطلب"),
            ("sent", "تم الإرسال"),
            ("delivered", "تم التسليم"),
            ("read", "تمت القراءة"),
            ("failed", "فشل"),
            ("pending", "قيد المتابعة"),
        ],
        string="النتيجة",
        compute="_compute_log_experience",
    )
    ui_kind = fields.Selection(
        [("test", "تجريبي"), ("live", "فعلي")],
        string="نوع التشغيل",
        compute="_compute_log_experience",
    )
    ui_summary = fields.Char(string="الملخص", compute="_compute_log_experience")
    ui_timeline = fields.Char(string="مسار الرسالة", compute="_compute_log_experience")
    ui_has_error = fields.Boolean(string="يوجد خطأ", compute="_compute_log_experience")

    @api.depends(
        "status",
        "delivery_status",
        "is_test",
        "error_message",
        "accepted_at",
        "sent_at",
        "delivered_at",
        "read_at",
        "failed_at",
        "last_webhook_status",
    )
    def _compute_log_experience(self):
        for log in self:
            raw_status = (log.status or "").strip().casefold()
            delivery = (log.delivery_status or "").strip().casefold()
            webhook = (log.last_webhook_status or "").strip().casefold()

            if raw_status == "read" or "read" in webhook:
                state = "read"
                summary = _("وصلت الرسالة وتمت قراءتها على WhatsApp.")
            elif raw_status == "delivered" or "delivered" in webhook:
                state = "delivered"
                summary = _("تم تسليم الرسالة إلى WhatsApp بنجاح.")
            elif raw_status == "sent" or "sent" in webhook:
                state = "sent"
                summary = _("تم إرسال الرسالة من WATI، وننتظر تحديث التسليم.")
            elif raw_status == "accepted" or delivery.startswith("accepted"):
                state = "accepted"
                summary = _("استلم WATI طلب الإرسال بنجاح، وننتظر تحديث حالة التسليم.")
            elif raw_status == "failed":
                state = "failed"
                summary = (log.error_message or _("تعذر إرسال الرسالة.")).strip()
            else:
                state = "pending"
                summary = _("التشغيل قيد المتابعة.")

            milestones = []
            if log.accepted_at or state in ("accepted", "sent", "delivered", "read"):
                milestones.append(_("قُبل"))
            if log.sent_at or state in ("sent", "delivered", "read"):
                milestones.append(_("أُرسل"))
            if log.delivered_at or state in ("delivered", "read"):
                milestones.append(_("تم التسليم"))
            if log.read_at or state == "read":
                milestones.append(_("تمت القراءة"))
            if state == "failed":
                milestones.append(_("فشل"))

            log.ui_state = state
            log.ui_kind = "test" if log.is_test else "live"
            log.ui_summary = summary[:500]
            log.ui_timeline = " ← ".join(milestones) if milestones else _("بانتظار تحديث WATI")
            log.ui_has_error = state == "failed"

    @api.model
    def _repair_false_negative_logs(self):
        """Reclassify only the proven WATI empty-error HTTP-2xx pattern.

        This does not claim that a message was delivered. It only corrects the
        API-boundary truth from ``failed`` to ``accepted``; Delivered/Read remain
        webhook-driven.
        """
        self.env.cr.execute(
            """
            UPDATE wati_automation_log
               SET status = 'accepted',
                   delivery_status = 'accepted_http_200_reclassified',
                   error_message = NULL,
                   accepted_at = COALESCE(accepted_at, create_date),
                   failed_at = NULL
             WHERE status = 'failed'
               AND delivery_status = 'api_failed'
               AND (
                    COALESCE(response_excerpt, '') || ' ' || COALESCE(error_message, '')
                   ) LIKE '%%"invalidWhatsappNumbers": []%%'
               AND (
                    COALESCE(response_excerpt, '') || ' ' || COALESCE(error_message, '')
                   ) LIKE '%%"invalidCustomParameters": []%%'
               AND (
                    COALESCE(response_excerpt, '') || ' ' || COALESCE(error_message, '')
                   ) LIKE '%%"error": ""%%'
            """
        )
        repaired = self.env.cr.rowcount
        if repaired:
            _logger.warning(
                "WATI_LOG_TRUTH_REPAIR reclassified=%s false-negative log(s) as accepted",
                repaired,
            )
        return repaired

    def init(self):
        self._repair_false_negative_logs()
