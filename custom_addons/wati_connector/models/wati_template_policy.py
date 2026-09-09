import re

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError

from ..services.feature_access import ensure_feature_access


_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:_[A-Z]{2})?$")
_PROTECTED_CONTENT_FIELDS = {
    "name",
    "language",
    "category",
    "body",
    "footer",
    "variable_ids",
    "template_kind",
    "builder_header_type",
    "builder_header_text",
    "header_media_url",
    "header_media_filename",
    "builder_button_type",
    "builder_button_text",
    "builder_button_url",
    "builder_button_phone",
}


class WatiTemplatePolicy(models.Model):
    _inherit = "wati.template"

    @api.model_create_multi
    def create(self, vals_list):
        ensure_feature_access(self.env, "templates")
        return super().create(vals_list)

    def write(self, vals):
        ensure_feature_access(self.env, "templates")
        if not self.env.su and _PROTECTED_CONTENT_FIELDS.intersection(vals):
            locked = self.filtered(
                lambda record: record.status != "draft" or record.source != "odoo"
            )
            if locked:
                raise UserError(
                    _(
                        "You can’t edit the content of a template after it’s been submitted for review or if it’s imported from WATI. Create a new copy and then edit the copy."
                    )
                )
        return super().write(vals)

    def unlink(self):
        ensure_feature_access(self.env, "templates")
        if not self.env.su:
            remote = self.filtered(
                lambda record: record.status != "draft"
                or record.wati_template_id
                or record.meta_template_id
                or record.waba_id
            )
            if remote:
                raise UserError(
                    _(
                        "Do not delete a template associated withWATI From a list Odoo directly. Use button «Delete from WATI / Meta» So the two cases remain identical."
                    )
                )
        return super().unlink()

    @api.constrains("language")
    def _check_language_code(self):
        for record in self:
            language = (record.language or "").strip()
            if not _LANGUAGE_RE.fullmatch(language):
                raise ValidationError(
                    _(
                        "Invalid language code. Use a formula like ar Or en Or en_US Or pt_BR."
                    )
                )

    @api.constrains("footer")
    def _check_footer_variables(self):
        for record in self:
            if "{{" in (record.footer or "") or "}}" in (record.footer or ""):
                raise ValidationError(
                    _("Do not put variables inside the footer. Place variables inside the main template body.")
                )
