from odoo import _, fields, models


class WatiAutomationRuleUIPolish(models.Model):
    _inherit = "wati.automation.rule"

    setup_step = fields.Selection(
        selection=[
            ("trigger", "1. Trigger"),
            ("recipient", "2. Recipient"),
            ("message", "3. Message"),
            ("review", "4. Review"),
        ]
    )

    def action_validate_template(self):
        """Verify WATI itself, but do not imply the whole message is ready.

        Template approval and variable mapping are separate checks. A template can
        be live/approved in WATI while the automation still has required
        placeholders with no Odoo value source. In that case keep the template
        verification valid, but return an explicit warning instead of the old
        green success notification.
        """
        self.ensure_one()
        self._validate_template_live(force=True, raise_error=True)

        total = self.template_parameter_count
        mapped = self.template_mapped_count
        mapping_ready = self.template_mapping_state in ("empty", "ready")

        if not mapping_ready:
            missing = max(0, total - mapped)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Template verified — message incomplete"),
                    "message": _(
                        "The WATI template is approved, but the automation message is not ready yet. "
                        "%(mapped)s of %(total)s variables are connected; %(missing)s still need a value source.",
                        mapped=mapped,
                        total=total,
                        missing=missing,
                    ),
                    "type": "warning",
                    "sticky": True,
                    "next": {"type": "ir.actions.client", "tag": "soft_reload"},
                },
            }

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Template verified — message ready"),
                "message": _(
                    "The WATI template is approved and all required template variables are connected."
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_send_test(self):
        """Surface the actual WATI failure instead of a generic test-send error."""
        self.ensure_one()
        result = super().action_send_test()
        params = result.get("params", {}) if isinstance(result, dict) else {}
        if params.get("type") != "danger":
            return result

        Log = self.env["wati.automation.log"].sudo()
        domain = [("rule_id", "=", self.id), ("is_test", "=", True)]
        phone = self._normalize_phone(self.test_phone)
        if phone:
            domain.append(("phone", "=", phone))
        log = Log.search(domain, order="create_date desc, id desc", limit=1)
        if not log:
            return result

        error = (log.error_message or "").strip()
        excerpt = (log.response_excerpt or "").strip()
        delivery_status = (getattr(log, "delivery_status", False) or "").strip()

        details = []
        if error:
            details.append(error[:700])
        if delivery_status:
            details.append("Delivery status: %s" % delivery_status)
        if excerpt and excerpt not in error:
            details.append("WATI response: %s" % excerpt[:900])

        if details:
            params.update(
                {
                    "title": _("WATI test send failed"),
                    "message": "\n".join(details),
                    "type": "danger",
                    "sticky": True,
                }
            )
        return result
