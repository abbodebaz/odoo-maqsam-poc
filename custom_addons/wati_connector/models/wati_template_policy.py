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
                        "لا يمكن تعديل محتوى قالب بعد إرساله للمراجعة أو إذا كان مستوردًا من WATI. أنشئ نسخة جديدة ثم عدّل النسخة."
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
                        "لا تحذف قالبًا مرتبطًا بـWATI من قائمة Odoo مباشرة. استخدم زر «حذف من WATI / Meta» حتى تبقى الحالتان متطابقتين."
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
                        "رمز اللغة غير صالح. استخدم صيغة مثل ar أو en أو en_US أو pt_BR."
                    )
                )

    @api.constrains("footer")
    def _check_footer_variables(self):
        for record in self:
            if "{{" in (record.footer or "") or "}}" in (record.footer or ""):
                raise ValidationError(
                    _("لا تضع متغيرات داخل التذييل. ضع المتغيرات داخل نص القالب الرئيسي.")
                )
