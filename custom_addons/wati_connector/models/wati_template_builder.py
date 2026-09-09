import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.template_catalog import clean


_TEMPLATE_KIND_SELECTION = [
    ("STANDARD", "Standard"),
    ("CATALOG", "Catalog"),
    ("CAROUSEL", "Carousel"),
    ("LIMITED_TIME_OFFER", "Limited-time offer"),
]

_HEADER_TYPE_SELECTION = [
    ("NONE", "Without"),
    ("TEXT", "Text"),
    ("IMAGE", "Image"),
    ("VIDEO", "Video"),
    ("DOCUMENT", "Document"),
]

_BUTTON_TYPE_SELECTION = [
    ("NONE", "No buttons"),
    ("QUICK_REPLY", "Fast reply"),
    ("URL", "Visit site"),
    ("PHONE", "Contact"),
]


class WatiTemplateBuilder(models.Model):
    _inherit = "wati.template"

    template_kind = fields.Selection(
        _TEMPLATE_KIND_SELECTION,
        string="Template type",
        default="STANDARD",
        required=True,
        copy=True,
    )
    builder_header_type = fields.Selection(
        _HEADER_TYPE_SELECTION,
        string="Header type",
        default="NONE",
        required=True,
        copy=True,
    )
    builder_header_text = fields.Char(string="Header text", copy=True)
    header_media_url = fields.Char(string="Media link", copy=True)
    header_media_filename = fields.Char(string="Document file name", copy=True)

    builder_button_type = fields.Selection(
        _BUTTON_TYPE_SELECTION,
        string="Button type",
        default="NONE",
        required=True,
        copy=True,
    )
    builder_button_text = fields.Char(string="Button text", copy=True)
    builder_button_url = fields.Char(string="Button link", copy=True)
    builder_button_phone = fields.Char(string="Contact number", copy=True)

    builder_header_preview = fields.Char(
        string="Header preview",
        compute="_compute_builder_preview",
    )
    builder_button_preview = fields.Char(
        string="Preview the button",
        compute="_compute_builder_preview",
    )
    advanced_kind_notice = fields.Char(
        string="Note advanced type",
        compute="_compute_advanced_kind_notice",
    )

    @api.depends(
        "builder_header_type",
        "builder_header_text",
        "header_media_filename",
        "builder_button_type",
        "builder_button_text",
    )
    def _compute_builder_preview(self):
        header_labels = {
            "IMAGE": "🖼️ Image",
            "VIDEO": "🎬 Video",
            "DOCUMENT": "📎 Document",
        }
        button_labels = {
            "QUICK_REPLY": "Fast reply",
            "URL": "Visit the website",
            "PHONE": "Contact",
        }
        for record in self:
            if record.builder_header_type == "TEXT":
                record.builder_header_preview = record.builder_header_text or "Message title"
            elif record.builder_header_type == "DOCUMENT" and record.header_media_filename:
                record.builder_header_preview = "📎 %s" % record.header_media_filename
            else:
                record.builder_header_preview = header_labels.get(record.builder_header_type, "")
            record.builder_button_preview = (
                record.builder_button_text
                or button_labels.get(record.builder_button_type, "")
            )

    @api.depends("template_kind")
    def _compute_advanced_kind_notice(self):
        notices = {
            "CATALOG": _(
                "selected Catalog. WATI This type is supported, but requires catalog settings/Additional products before submitting for review."
            ),
            "CAROUSEL": _(
                "selected Carousel. WATI This type is supported, but requires the preparation of cards and the content of each card before sending for review."
            ),
            "LIMITED_TIME_OFFER": _(
                "selected Limited-time offer. WATI This type is supported, but requires display data and end time to be set before submission for review."
            ),
        }
        for record in self:
            record.advanced_kind_notice = notices.get(record.template_kind, "")

    @api.onchange("template_kind")
    def _onchange_template_kind_builder(self):
        for record in self:
            record.sub_category = record.template_kind or "STANDARD"

    @api.onchange("builder_header_type")
    def _onchange_builder_header_type(self):
        for record in self:
            if record.builder_header_type != "TEXT":
                record.builder_header_text = False
            if record.builder_header_type not in {"IMAGE", "VIDEO", "DOCUMENT"}:
                record.header_media_url = False
            if record.builder_header_type != "DOCUMENT":
                record.header_media_filename = False

    @api.onchange("builder_button_type")
    def _onchange_builder_button_type(self):
        for record in self:
            if record.builder_button_type == "NONE":
                record.builder_button_text = False
                record.builder_button_url = False
                record.builder_button_phone = False
            elif record.builder_button_type == "QUICK_REPLY":
                record.builder_button_url = False
                record.builder_button_phone = False
            elif record.builder_button_type == "URL":
                record.builder_button_phone = False
            elif record.builder_button_type == "PHONE":
                record.builder_button_url = False

    @api.model_create_multi
    def create(self, vals_list):
        prepared = [self._prepare_builder_vals(vals) for vals in vals_list]
        return super().create(prepared)

    def write(self, vals):
        return super().write(self._prepare_builder_vals(vals))

    @api.model
    def _prepare_builder_vals(self, vals):
        values = dict(vals or {})
        source = values.get("source")
        if source == "wati":
            return values

        kind = values.get("template_kind")
        if kind:
            values["sub_category"] = kind

        header_type = values.get("builder_header_type")
        if header_type:
            values["header_type"] = False if header_type == "NONE" else header_type
            if header_type == "TEXT" and "builder_header_text" in values:
                values["header_text"] = values.get("builder_header_text") or False
            elif header_type != "TEXT":
                values["header_text"] = False

        button_type = values.get("builder_button_type")
        if button_type:
            values["buttons_json"] = json.dumps(
                self._button_payload_from_values(values),
                ensure_ascii=False,
            )
        return values

    @api.model
    def _button_payload_from_values(self, values):
        button_type = values.get("builder_button_type") or "NONE"
        text = clean(values.get("builder_button_text"))
        if button_type == "NONE":
            return []
        if button_type == "QUICK_REPLY":
            return [{"type": "quick_reply", "text": text}]
        if button_type == "URL":
            return [
                {
                    "type": "url",
                    "text": text,
                    "url": clean(values.get("builder_button_url")),
                }
            ]
        if button_type == "PHONE":
            return [
                {
                    "type": "call",
                    "text": text,
                    "phoneNumber": clean(values.get("builder_button_phone")),
                }
            ]
        return []

    def _button_payload(self):
        self.ensure_one()
        return self._button_payload_from_values(
            {
                "builder_button_type": self.builder_button_type,
                "builder_button_text": self.builder_button_text,
                "builder_button_url": self.builder_button_url,
                "builder_button_phone": self.builder_button_phone,
            }
        )

    def _header_payload(self):
        self.ensure_one()
        header_type = self.builder_header_type or "NONE"
        if header_type == "NONE":
            return {}
        if header_type == "TEXT":
            return {
                "type": "Text",
                "text": self.builder_header_text or "",
            }
        media = {"url": self.header_media_url or ""}
        if header_type == "DOCUMENT":
            media["fileName"] = self.header_media_filename or ""
        return {
            "type": header_type.title(),
            "media": media,
        }

    def _buttons_type_payload(self):
        self.ensure_one()
        if self.builder_button_type == "NONE":
            return "NONE"
        if self.builder_button_type == "QUICK_REPLY":
            return "quick_reply"
        return "call_to_action"

    def _assert_can_submit(self):
        super()._assert_can_submit()
        self.ensure_one()

        if self.template_kind != "STANDARD":
            raise UserError(
                _(
                    "Type %s It has been selected successfully, but submitting it for review requires its own advanced settings within WATI. You can save the draft now, and we will activate its specialized editor without submitting Payload Minus to Meta."
                )
                % self.template_kind
            )

        if self.builder_header_type == "TEXT":
            if not clean(self.builder_header_text):
                raise UserError(_("Write the header text before submitting the template for review."))
            if len(self.builder_header_text or "") > 60:
                raise ValidationError(_("Header text overflow 60 A letter."))
        elif self.builder_header_type in {"IMAGE", "VIDEO", "DOCUMENT"}:
            if not clean(self.header_media_url):
                raise UserError(_("Enter the media link used in the template header."))
            if self.builder_header_type == "DOCUMENT" and not clean(self.header_media_filename):
                raise UserError(_("Enter the file name of the document, e.g: invoice.pdf"))

        if self.builder_button_type != "NONE":
            if not clean(self.builder_button_text):
                raise UserError(_("Type the button text before submitting the template for review."))
            if len(self.builder_button_text or "") > 20:
                raise ValidationError(_("Override button text 20 A letter."))
        if self.builder_button_type == "URL" and not clean(self.builder_button_url):
            raise UserError(_("Enter the link to the visit website button."))
        if self.builder_button_type == "PHONE" and not clean(self.builder_button_phone):
            raise UserError(_("Enter the phone number for the call button."))

    def _build_submission_payload(self):
        self.ensure_one()
        payload = super()._build_submission_payload()
        payload.update(
            {
                "subCategory": self.template_kind or "STANDARD",
                "header": self._header_payload(),
                "buttonsType": self._buttons_type_payload(),
                "buttons": self._button_payload(),
            }
        )
        return payload

    @api.model
    def _remote_values(self, normalized, now=None):
        values = super()._remote_values(normalized, now=now)
        sub_category = clean(normalized.get("sub_category")).upper() or "STANDARD"
        values["template_kind"] = (
            sub_category
            if sub_category in dict(_TEMPLATE_KIND_SELECTION)
            else "STANDARD"
        )

        header_type = clean(normalized.get("header_type")).upper()
        values["builder_header_type"] = (
            header_type if header_type in dict(_HEADER_TYPE_SELECTION) else "NONE"
        )
        values["builder_header_text"] = normalized.get("header_text") or False

        buttons = normalized.get("buttons") or []
        if buttons and isinstance(buttons[0], dict):
            button = buttons[0]
            button_type = clean(button.get("type")).casefold()
            if button_type in {"quick_reply", "quickreply"}:
                values["builder_button_type"] = "QUICK_REPLY"
            elif button_type in {"url", "website"}:
                values["builder_button_type"] = "URL"
            elif button_type in {"call", "phone_number", "phone"}:
                values["builder_button_type"] = "PHONE"
            else:
                values["builder_button_type"] = "NONE"
            values["builder_button_text"] = clean(button.get("text")) or False
            values["builder_button_url"] = clean(
                button.get("url") or button.get("targetUrl") or button.get("originalUrl")
            ) or False
            values["builder_button_phone"] = clean(
                button.get("phoneNumber") or button.get("phone_number")
            ) or False
        else:
            values["builder_button_type"] = "NONE"
            values["builder_button_text"] = False
            values["builder_button_url"] = False
            values["builder_button_phone"] = False
        return values
