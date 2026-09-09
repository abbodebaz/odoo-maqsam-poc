import re

from odoo import _, api, fields, models


class WatiAutomationRuleReview(models.Model):
    _inherit = "wati.automation.rule"

    preview_mode = fields.Selection(
        [
            ("real", "Real data"),
            ("sample", "Experimental data"),
        ],
        string="Preview type",
        copy=False,
        readonly=True,
    )
    preview_source_note = fields.Char(
        string="Preview source",
        copy=False,
        readonly=True,
    )
    preview_generated_at = fields.Datetime(
        string="Preview time",
        copy=False,
        readonly=True,
    )
    review_message_summary = fields.Char(
        string="Message summary",
        compute="_compute_review_message_summary",
    )

    @api.depends("template_name", "parameter_ids", "parameter_ids.param_name")
    def _compute_review_message_summary(self):
        for rule in self:
            if not rule.template_name:
                rule.review_message_summary = _("No template has been selected yet")
                continue
            count = len(rule.parameter_ids)
            if count:
                rule.review_message_summary = _("%s · %s variable", rule.template_name, count)
            else:
                rule.review_message_summary = _("%s · No variables", rule.template_name)

    def _sample_value_for_parameter(self, line):
        """Return a harmless human-looking value for preview-only rendering."""
        if line.source_type == "record_id":
            return "123"
        if line.source_type == "record_name":
            return _("Demo record")
        if line.source_type == "static" and (line.static_value or "").strip():
            return line.static_value

        field = line.source_field_id
        field_name = ""
        field_type = ""
        if field:
            field_name = (field.name or "").casefold()
            field_type = (field.ttype or "").casefold()
        elif (line.source_path or "").strip():
            field_name = line.source_path.rsplit(".", 1)[-1].casefold()

        if any(token in field_name for token in ("mobile", "phone", "whatsapp", "tel")):
            return "9665XXXXXXX"
        if "email" in field_name:
            return "example@company.com"
        if field_type == "date" or "date" in field_name:
            return "2026-09-09"
        if field_type == "datetime" or "time" in field_name:
            return "2026-09-09 10:30"
        if field_type in ("integer", "float", "monetary") or any(
            token in field_name for token in ("amount", "total", "price", "cost")
        ):
            return "1,250"
        if any(token in field_name for token in ("stage", "status", "state")):
            return _("Experimental phase")
        if any(token in field_name for token in ("name", "title", "partner", "customer", "client")):
            return _("Demo client")

        label = ""
        if field:
            label = field.field_description or field.name or ""
        if not label:
            label = (line.param_name or "").strip()
        return _("Experimental value") if not label else _("Example: %s", label)

    def _render_safe_sample_preview(self):
        self.ensure_one()
        body = self.template_body or ""
        rendered = body
        for line in self.parameter_ids.sorted("sequence"):
            if not line.param_name:
                continue
            value = self._sample_value_for_parameter(line)
            rendered = re.sub(
                r"{{\s*" + re.escape(str(line.param_name)) + r"\s*}}",
                str(value),
                rendered,
            )
        if not rendered:
            rendered = _(
                "Template «%s» Ready, but WATI The template text was not sent for preview.",
                self.template_name,
            )
        return rendered

    def _write_preview(self, text, mode, source_note, record_name=False):
        self.ensure_one()
        self.write({
            "preview_text": text,
            "preview_record_name": record_name or False,
            "preview_mode": mode,
            "preview_source_note": source_note,
            "preview_generated_at": fields.Datetime.now(),
        })

    def action_preview_latest_record(self):
        """Always produce a preview.

        Prefer a real Odoo record when one exists. On fresh databases where the
        selected model has no records yet, fall back to safe synthetic values
        instead of blocking the user with an error.
        """
        self.ensure_one()
        if not self.template_name:
            from odoo.exceptions import UserError

            raise UserError(_("Choose a template WATI First."))

        record = self._sample_record() if self.model_id else False
        if record:
            record_name = record.display_name or str(record.id)
            self._write_preview(
                self._render_preview(record),
                "real",
                _("Preview with real data from Odoo: %s", record_name),
                record_name=record_name,
            )
            message = _("The preview was created using history: %s", record_name)
        else:
            self._write_preview(
                self._render_safe_sample_preview(),
                "sample",
                _("No records yet; We used safe experimental data for preview only."),
            )
            message = _("There’s no actual data yet, so we created a safe beta preview.")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("The preview is ready"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_preview_sample(self):
        self.ensure_one()
        if not self.template_name:
            from odoo.exceptions import UserError

            raise UserError(_("Choose a template WATI First."))
        self._write_preview(
            self._render_safe_sample_preview(),
            "sample",
            _("Safe demo preview; No message will be sent and no data will be changed Odoo."),
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("A test preview has been created"),
                "message": _("This preview is for display only and does not send any information WhatsApp."),
                "type": "info",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
