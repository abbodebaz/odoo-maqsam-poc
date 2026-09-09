import re

from odoo import _, api, models
from odoo.exceptions import ValidationError

from ..services.template_catalog import clean, extract_placeholders, placeholder_mode


_TEMPLATE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NAMED_VARIABLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class WatiTemplateProviderPolicy(models.Model):
    """Keep provider snapshots faithful while validating Odoo-authored drafts.

    WATI/Meta is the source of truth for imported templates. Provider records
    must be stored exactly as returned, even when an older/provider-side
    template does not satisfy the stricter authoring rules we enforce for new
    templates created in Odoo.
    """

    _inherit = "wati.template"

    @api.constrains("name", "language", "source")
    def _check_identity(self):
        for record in self:
            name = clean(record.name)

            if record.source == "odoo":
                if len(name) > 512 or not _TEMPLATE_NAME_RE.fullmatch(name):
                    raise ValidationError(
                        _(
                            "اسم القالب يجب أن يبدأ بحرف إنجليزي صغير ويحتوي فقط على أحرف إنجليزية صغيرة وأرقام وشرطة سفلية (_). مثال: order_ready_ar"
                        )
                    )

            duplicate = self.search_count(
                [
                    ("id", "!=", record.id),
                    ("name", "=", name),
                    ("language", "=", clean(record.language)),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _("يوجد قالب بنفس الاسم واللغة بالفعل. الاسم واللغة يجب أن يكونا فريدين.")
                )

    @api.constrains("body", "footer", "source")
    def _check_content_limits(self):
        for record in self:
            if record.source != "odoo":
                continue
            body = record.body or ""
            footer = record.footer or ""
            if not body.strip():
                raise ValidationError(_("نص القالب لا يمكن أن يكون فارغًا."))
            if len(body) > 1024:
                raise ValidationError(_("نص القالب تجاوز 1024 حرفًا."))
            if len(footer) > 60:
                raise ValidationError(_("تذييل القالب تجاوز 60 حرفًا."))

    @api.constrains("body", "source")
    def _check_placeholder_contract(self):
        for record in self:
            if record.source != "odoo":
                continue
            tokens = extract_placeholders(record.body)
            mode = placeholder_mode(tokens)
            if mode == "mixed":
                raise ValidationError(
                    _("لا تخلط بين متغيرات مرقمة مثل {{1}} ومتغيرات مسماة مثل {{name}} في القالب نفسه.")
                )
            if mode == "positional":
                expected = [str(index) for index in range(1, len(tokens) + 1)]
                if tokens != expected:
                    raise ValidationError(
                        _("المتغيرات المرقمة يجب أن تكون متسلسلة بالترتيب: {{1}}, {{2}}, {{3}} ...")
                    )
            if mode == "named":
                invalid = [token for token in tokens if not _NAMED_VARIABLE_RE.fullmatch(token)]
                if invalid:
                    raise ValidationError(
                        _("اسم المتغير غير صالح: %s. استخدم أحرفًا إنجليزية وأرقامًا وشرطة سفلية فقط.")
                        % invalid[0]
                    )

    @api.onchange("name")
    def _onchange_name_authoring_helper(self):
        """Apply harmless formatting assistance while the user is authoring.

        Lowercasing and converting whitespace/dashes to underscores mirrors
        the provider naming convention without silently stripping meaningful
        characters. Any remaining invalid character is still rejected on save.
        """
        for record in self:
            if record.source != "odoo" or record.status != "draft" or not record.name:
                continue
            normalized = clean(record.name).lower()
            normalized = re.sub(r"[\s\-]+", "_", normalized)
            normalized = re.sub(r"_+", "_", normalized)
            record.name = normalized
