import re

from odoo import _, api, fields, models

from ..services.template_catalog import clean


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:_[A-Z]{2})?$")


class WatiTemplateReadiness(models.Model):
    _inherit = "wati.template"

    body_char_count = fields.Integer(string="Body characters", compute="_compute_template_readiness")
    footer_char_count = fields.Integer(string="Footer characters", compute="_compute_template_readiness")
    readiness_state = fields.Selection(
        [("ready", "Ready"), ("attention", "Needs attention")],
        string="Review readiness",
        compute="_compute_template_readiness",
    )
    readiness_message = fields.Text(string="Readiness details", compute="_compute_template_readiness")
    readiness_missing_count = fields.Integer(string="Missing items", compute="_compute_template_readiness")

    @api.depends(
        "name", "language", "category", "template_kind", "body", "footer",
        "variable_ids.name", "variable_ids.sample_value",
        "builder_header_type", "builder_header_text", "header_media_url", "header_media_filename",
        "builder_button_type", "builder_button_text", "builder_button_url", "builder_button_phone",
    )
    def _compute_template_readiness(self):
        for record in self:
            issues = []
            body = record.body or ""
            footer = record.footer or ""
            record.body_char_count = len(body)
            record.footer_char_count = len(footer)

            name = clean(record.name)
            if not name:
                issues.append(_("Add a template name."))
            elif len(name) > 512 or not _NAME_RE.fullmatch(name):
                issues.append(_("Template name must use lowercase letters, numbers and underscores only."))

            language = clean(record.language)
            if not language:
                issues.append(_("Choose a language code."))
            elif not _LANGUAGE_RE.fullmatch(language):
                issues.append(_("Use a valid language code such as ar, en or en_US."))

            if record.category not in {"UTILITY", "MARKETING"}:
                issues.append(_("Choose Utility or Marketing for templates created in Odoo."))
            if record.template_kind != "STANDARD":
                issues.append(_("This advanced template type needs its dedicated WATI editor before submission."))
            if not body.strip():
                issues.append(_("Write the message text."))
            elif len(body) > 1024:
                issues.append(_("Message text is longer than 1024 characters."))
            if len(footer) > 60:
                issues.append(_("Footer is longer than 60 characters."))
            if "{{" in footer or "}}" in footer:
                issues.append(_("Footer cannot contain variables."))

            missing_samples = record.variable_ids.filtered(lambda line: not clean(line.sample_value))
            if missing_samples:
                issues.append(
                    _("Add example values for: %s") % ", ".join(missing_samples.mapped("name"))
                )

            if record.builder_header_type == "TEXT" and not clean(record.builder_header_text):
                issues.append(_("Add the header text."))
            elif record.builder_header_type in {"IMAGE", "VIDEO", "DOCUMENT"}:
                if not clean(record.header_media_url):
                    issues.append(_("Add the header media URL."))
                if record.builder_header_type == "DOCUMENT" and not clean(record.header_media_filename):
                    issues.append(_("Add the document file name."))

            if record.builder_button_type != "NONE" and not clean(record.builder_button_text):
                issues.append(_("Add the button label."))
            if record.builder_button_type == "URL" and not clean(record.builder_button_url):
                issues.append(_("Add the button destination URL."))
            if record.builder_button_type == "PHONE" and not clean(record.builder_button_phone):
                issues.append(_("Add the button phone number."))

            record.readiness_missing_count = len(issues)
            record.readiness_state = "attention" if issues else "ready"
            record.readiness_message = "\n".join("• %s" % issue for issue in issues) if issues else _(
                "Everything required is complete. Review the final message, then submit it to WATI / Meta."
            )

    def action_open_submit_review(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Review template before submission"),
            "res_model": "wati.template",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("wati_connector.view_wati_template_submit_review").id,
            "target": "new",
            "context": dict(self.env.context, form_view_initial_mode="readonly"),
        }
