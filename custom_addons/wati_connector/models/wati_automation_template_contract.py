import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .wati_automation_improvements import (
    _dedupe_names,
    _template_body,
    _template_body_tokens,
    _template_custom_param_names,
    _template_name,
)
from .wati_automation_guard import (
    _same_channel,
    _template_category,
    _template_channel,
    _template_language,
    _template_status,
)


_logger = logging.getLogger(__name__)
_APPROVED_STATES = {"approved", "active", "enabled", "live"}
_GENERIC_TEMPLATE_NAMES = {"whatsapp", "wati", "unknown", "none", "null"}


def _template_external_id(item):
    if not isinstance(item, dict):
        return ""
    for key in (
        "id",
        "templateId",
        "template_id",
        "whatsappTemplateId",
        "whatsapp_template_id",
        "elementId",
    ):
        value = item.get(key)
        if value not in (None, "", False):
            return str(value).strip()
    return ""


def _loads_contract(raw):
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _normalise_slots(slots):
    result = []
    seen_tokens = set()
    for index, slot in enumerate(slots or [], start=1):
        if not isinstance(slot, dict):
            continue
        token = str(slot.get("token") or "").strip()
        api_name = str(slot.get("api_name") or "").strip()
        if not token:
            continue
        key = token.casefold()
        if key in seen_tokens:
            continue
        seen_tokens.add(key)
        result.append(
            {
                "position": index,
                "token": token,
                "api_name": api_name,
            }
        )
    return result


def _build_template_contract(item):
    """Build one deterministic contract between visible placeholders and WATI API names.

    WATI's send APIs require parameter names to match the template definition
    exactly. The WhatsApp body can still display positional placeholders such as
    ``{{1}}`` while WATI exposes a semantic custom parameter name such as
    ``name``. Those are two representations of the same slot and must never be
    collapsed into one field.

    The contract is deliberately fail-closed. If WATI reports a different
    number of API parameter names than the visible template body exposes, the
    automation is marked invalid instead of guessing and risking a production
    send failure.
    """
    body_tokens = _dedupe_names(_template_body_tokens(item))
    api_names = _dedupe_names(_template_custom_param_names(item))
    slots = []
    state = "valid"
    source = "body"

    if body_tokens and api_names:
        if len(body_tokens) == len(api_names):
            # Named placeholders can be matched by name. Positional placeholders
            # are paired by WATI's declared customParams order.
            api_by_key = {name.casefold(): name for name in api_names}
            if all(not token.isdigit() for token in body_tokens) and all(
                token.casefold() in api_by_key for token in body_tokens
            ):
                slots = [
                    {"token": token, "api_name": api_by_key[token.casefold()]}
                    for token in body_tokens
                ]
            else:
                slots = [
                    {"token": token, "api_name": api_name}
                    for token, api_name in zip(body_tokens, api_names)
                ]
            source = "body+wati"
        else:
            state = "invalid"
            source = "mismatch"
            api_by_key = {name.casefold(): name for name in api_names}
            slots = [
                {
                    "token": token,
                    "api_name": api_by_key.get(token.casefold(), ""),
                }
                for token in body_tokens
            ]
    elif body_tokens:
        # WATI sometimes exposes no customParams metadata. Its documented API
        # accepts positional names ("1", "2", ...) when those are the template
        # parameter names, so the visible token is the safe fallback.
        slots = [{"token": token, "api_name": token} for token in body_tokens]
        source = "body-fallback"
    elif api_names:
        # Some template types expose their variable contract only through WATI
        # metadata. Keep those sendable, but show the semantic name to the user.
        slots = [{"token": name, "api_name": name} for name in api_names]
        source = "wati-only"
    else:
        source = "none"

    slots = _normalise_slots(slots)
    if state == "invalid":
        message = _(
            "WATI يعرّف %(api)s متغيرات للإرسال بينما نص القالب يعرض %(body)s. "
            "تم منع التفعيل حتى يتطابق عقد القالب بدل التخمين.",
            api=len(api_names),
            body=len(body_tokens),
        )
    elif slots and any(slot["token"] != slot["api_name"] for slot in slots):
        message = _(
            "تمت مطابقة %(count)s متغيرات ظاهرة مع أسماء WATI API الحقيقية. الإرسال متطابق.",
            count=len(slots),
        )
    elif slots:
        message = _("عقد متغيرات WATI متطابق: %s متغيرات.", len(slots))
    else:
        message = _("هذا القالب لا يحتاج متغيرات للإرسال.")

    return {
        "version": 1,
        "state": state,
        "source": source,
        "template_name": _template_name(item),
        "template_id": _template_external_id(item),
        "language": _template_language(item),
        "channel": _template_channel(item),
        "body_tokens": body_tokens,
        "api_names": api_names,
        "slots": slots,
        "message": message,
    }


class WatiAutomationRuleTemplateContract(models.Model):
    _inherit = "wati.automation.rule"

    template_external_id = fields.Char(
        string="WATI Template ID",
        readonly=True,
        copy=False,
    )
    template_contract_json = fields.Text(
        string="عقد متغيرات WATI",
        readonly=True,
        copy=False,
    )
    template_contract_state = fields.Selection(
        [
            ("unknown", "غير مفحوص"),
            ("valid", "متطابق"),
            ("invalid", "غير متطابق"),
        ],
        string="تطابق متغيرات WATI",
        default="unknown",
        readonly=True,
        copy=False,
        index=True,
    )
    template_contract_message = fields.Text(
        string="نتيجة تطابق المتغيرات",
        readonly=True,
        copy=False,
    )

    def _contract(self):
        self.ensure_one()
        return _loads_contract(self.template_contract_json)

    def _store_contract(self, contract):
        self.ensure_one()
        contract = contract or {}
        state = contract.get("state") or "unknown"
        message = contract.get("message") or ""
        self.with_context(wati_contract_internal=True, wati_guard_internal=True).write(
            {
                "template_contract_json": json.dumps(contract, ensure_ascii=False),
                "template_contract_state": state,
                "template_contract_message": message or False,
                "template_external_id": contract.get("template_id") or False,
            }
        )

    def _apply_template_contract(self, contract=None, reason="runtime"):
        Parameter = self.env["wati.automation.parameter"].sudo()
        for rule in self.sudo():
            current = contract if len(self) == 1 and contract is not None else rule._contract()
            slots = _normalise_slots(current.get("slots") or [])
            rows = Parameter.search([("rule_id", "=", rule.id)], order="sequence, id")

            by_token = {}
            by_api = {}
            for row in rows:
                token_key = (
                    row.placeholder_token
                    or row.param_name
                    or ""
                ).strip().casefold()
                api_key = (
                    row.api_param_name
                    or row.param_name
                    or ""
                ).strip().casefold()
                if token_key and token_key not in by_token:
                    by_token[token_key] = row
                if api_key and api_key not in by_api:
                    by_api[api_key] = row

            used_ids = set()
            keep_ids = set()
            for index, slot in enumerate(slots, start=1):
                token = slot["token"]
                api_name = slot["api_name"]
                row = by_token.get(token.casefold())
                if not row and api_name:
                    candidate = by_api.get(api_name.casefold())
                    if candidate and candidate.id not in used_ids:
                        row = candidate
                if row and row.id in used_ids:
                    row = False

                vals = {
                    "param_name": token,
                    "placeholder_token": token,
                    "api_param_name": api_name or False,
                    "sequence": index * 10,
                }
                if row:
                    row.write(vals)
                    used_ids.add(row.id)
                    keep_ids.add(row.id)
                else:
                    vals.update(
                        {
                            "rule_id": rule.id,
                            "source_type": "field",
                        }
                    )
                    row = Parameter.create(vals)
                    used_ids.add(row.id)
                    keep_ids.add(row.id)

            stale = rows.filtered(lambda row: row.id not in keep_ids)
            if stale:
                stale.unlink()

            rule.invalidate_recordset(["parameter_ids"])
            final_rows = Parameter.search(
                [("rule_id", "=", rule.id)], order="sequence, id"
            )
            _logger.warning(
                "WATI_TEMPLATE_CONTRACT_APPLY rule=%s template=%r reason=%s state=%s slots=%s rows=%s",
                rule.id,
                rule.template_name,
                reason,
                current.get("state") or "unknown",
                [(slot["token"], slot["api_name"]) for slot in slots],
                [
                    (row.param_name, row.api_param_name)
                    for row in final_rows
                ],
            )
        return True

    def _sync_contract_from_item(self, item, reason="live"):
        self.ensure_one()
        contract = _build_template_contract(item)
        self._store_contract(contract)
        self._apply_template_contract(contract, reason=reason)
        # Keep the legacy cache aligned with visible placeholders only. It is no
        # longer used as the API parameter name source.
        self.with_context(wati_contract_internal=True, wati_guard_internal=True).write(
            {
                "template_param_names_json": json.dumps(
                    [slot["token"] for slot in contract.get("slots") or []],
                    ensure_ascii=False,
                )
            }
        )
        return contract

    def _hard_rebuild_template_parameters(self, reason="runtime"):
        # This method is intentionally overridden after the legacy integrity
        # layer. If a verified contract exists, rebuilding must preserve the API
        # name alias instead of collapsing everything back to {{1}}, {{2}}, ...
        contract = self._contract() if len(self) == 1 else {}
        if contract.get("slots") is not None and self.template_contract_state in (
            "valid",
            "invalid",
        ):
            return self._apply_template_contract(contract, reason=reason)
        return super()._hard_rebuild_template_parameters(reason=reason)

    def _select_live_template(self, templates=None):
        self.ensure_one()
        templates = templates if templates is not None else self._fetch_wati_templates_guarded()
        wanted = (self.template_name or "").strip().casefold()
        candidates = [
            item
            for item in templates
            if _template_name(item).strip().casefold() == wanted
        ]

        # Once the user selected a concrete language/ID, never silently switch
        # to another variant with the same name during validation or sending.
        wanted_id = (self.template_external_id or "").strip()
        if wanted_id:
            by_id = [item for item in candidates if _template_external_id(item) == wanted_id]
            if by_id:
                candidates = by_id
        wanted_language = (self.template_language or "").strip().casefold()
        if wanted_language and candidates:
            by_language = [
                item
                for item in candidates
                if _template_language(item).strip().casefold() == wanted_language
            ]
            if not by_language:
                return None, _(
                    "القالب «%(name)s» موجود لكن النسخة المختارة باللغة %(lang)s لم تعد متاحة. "
                    "اختر القالب من جديد قبل التفعيل.",
                    name=self.template_name,
                    lang=self.template_language,
                )
            candidates = by_language

        return super()._select_live_template(candidates)

    def _store_template_validation(self, item=None, error=""):
        result = super()._store_template_validation(item=item, error=error)
        for rule in self:
            if item:
                rule._sync_contract_from_item(item, reason="live_validation")
            elif error:
                rule.with_context(wati_contract_internal=True).write(
                    {
                        "template_contract_state": "unknown",
                        "template_contract_message": error,
                    }
                )
        return result

    def _validate_template_live(self, force=False, raise_error=True):
        valid = super()._validate_template_live(force=force, raise_error=raise_error)
        if not valid:
            return False

        for rule in self:
            if rule.template_contract_state == "unknown":
                try:
                    templates = rule._fetch_wati_templates_guarded()
                    item, error = rule._select_live_template(templates)
                    if item:
                        rule._sync_contract_from_item(item, reason="contract_refresh")
                    else:
                        rule.with_context(wati_contract_internal=True).write(
                            {
                                "template_contract_state": "invalid",
                                "template_contract_message": error or _("تعذر تحديد عقد القالب."),
                            }
                        )
                except Exception as exc:
                    _logger.exception("Could not refresh WATI template contract for rule %s", rule.id)
                    rule.with_context(wati_contract_internal=True).write(
                        {
                            "template_contract_state": "unknown",
                            "template_contract_message": str(exc)[:800],
                        }
                    )

            if rule.template_contract_state != "valid":
                message = rule.template_contract_message or _(
                    "لم يتم التحقق من تطابق متغيرات القالب مع WATI."
                )
                if raise_error:
                    raise ValidationError(
                        _("لا يمكن تفعيل/إرسال الأتمتة:\n%s") % message
                    )
                return False
        return True

    def action_pick_template(self):
        self.ensure_one()
        effective_channel = self._effective_channel()
        if not effective_channel:
            raise UserError(
                _("حدد رقم قناة WATI في الإعدادات أولًا قبل اختيار القالب.")
            )

        templates = self._fetch_wati_templates_guarded()
        Choice = self.env["wati.automation.template.choice"]
        Choice.search([("rule_id", "=", self.id)]).unlink()
        values = []
        for item in templates:
            name = _template_name(item).strip()
            if not name or name.casefold() in _GENERIC_TEMPLATE_NAMES:
                continue
            status = _template_status(item).strip()
            channel = _template_channel(item).strip()
            if status.casefold() not in _APPROVED_STATES:
                continue
            if channel and not _same_channel(channel, effective_channel):
                continue
            contract = _build_template_contract(item)
            values.append(
                {
                    "rule_id": self.id,
                    "name": name,
                    "status": status,
                    "category": _template_category(item),
                    "body": _template_body(item),
                    "language": _template_language(item),
                    "channel_number": channel or effective_channel,
                    "template_external_id": _template_external_id(item),
                    "contract_json": json.dumps(contract, ensure_ascii=False),
                }
            )

        if not values:
            raise UserError(
                _("لم أجد أي قالب Approved صالح لقناة WATI الحالية.")
            )

        unique = {}
        for vals in values:
            key = (
                vals["name"].casefold(),
                (vals["language"] or "").casefold(),
                re.sub(r"\D+", "", vals["channel_number"] or ""),
            )
            unique[key] = vals
        Choice.create(list(unique.values()))

        return {
            "type": "ir.actions.act_window",
            "name": _("اختر قالب WATI المعتمد"),
            "res_model": "wati.automation.template.choice",
            "view_mode": "list",
            "views": [
                (
                    self.env.ref(
                        "wati_connector.view_wati_automation_template_choice_list"
                    ).id,
                    "list",
                )
            ],
            "domain": [("rule_id", "=", self.id)],
            "target": "new",
        }

    def action_fetch_template_params(self):
        self.ensure_one()
        if not self.template_name:
            raise UserError(_("اختر قالب WATI أولًا."))
        self._validate_template_live(force=True, raise_error=True)
        mapped = self._auto_map_parameters()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تمت مزامنة عقد القالب"),
                "message": (
                    (self.template_contract_message or "")
                    + (_(" تم اقتراح %s ربط تلقائي.", mapped) if mapped else "")
                ).strip(),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _auto_map_parameters(self):
        self.ensure_one()
        if not self.model_id:
            return 0
        Fields = self.env["ir.model.fields"].sudo()
        model_fields = Fields.search([("model_id", "=", self.model_id.id)])
        by_name = {field.name.casefold(): field for field in model_fields}
        mapped = 0
        for line in self.parameter_ids:
            if line.source_type != "field" or line.source_field_id or (line.source_path or "").strip():
                continue
            semantic_name = line.api_param_name or line.param_name or ""
            key = re.sub(r"[^a-z0-9]+", "_", semantic_name.casefold()).strip("_")
            target_field = by_name.get(key)
            vals = {}
            if target_field:
                vals["source_field_id"] = target_field.id
            elif any(token in key for token in ("client", "customer", "contact")) and "partner_id" in by_name:
                vals["source_path"] = "partner_id.name"
            elif key in ("id", "record_id") or key.endswith("_id2") or key.endswith("_id"):
                vals["source_type"] = "record_id"
            elif any(token in key for token in ("dep", "department", "team")) and "team_id" in by_name:
                vals["source_path"] = "team_id.name"
            elif any(token in key for token in ("name", "title", "sap")) and "name" in by_name:
                vals["source_field_id"] = by_name["name"].id
            if vals:
                line.write(vals)
                mapped += 1
        return mapped

    @api.depends(
        "template_contract_state",
        "template_contract_message",
        "parameter_ids.api_param_name",
        "parameter_ids.placeholder_token",
    )
    def _compute_ux_state(self):
        super()._compute_ux_state()
        for rule in self:
            if not rule.template_name:
                continue
            current = rule.readiness_message or ""
            if rule.template_contract_state == "valid":
                line = "✅ عقد متغيرات WATI متطابق"
                if line not in current:
                    rule.readiness_message = (current + "\n" + line).strip()
            else:
                rule.readiness_state = "incomplete"
                line = "❌ " + (
                    rule.template_contract_message
                    or "لم يتم التحقق من عقد متغيرات WATI."
                )
                if line not in current:
                    rule.readiness_message = (current + "\n" + line).strip()

    def _contract_send_params(self, record):
        self.ensure_one()
        contract = self._contract()
        slots = _normalise_slots(contract.get("slots") or [])
        expected_names = [slot["api_name"] for slot in slots]
        rows = self.parameter_ids.sorted("sequence")
        params = []
        for row in rows:
            api_name = (row.api_param_name or row.param_name or "").strip()
            if not api_name:
                continue
            params.append(
                {
                    "name": api_name,
                    "value": self._parameter_value(record, row),
                }
            )

        actual_names = [item["name"] for item in params]
        if actual_names != expected_names:
            return [], _(
                "عقد الإرسال غير متطابق. WATI يتوقع %(expected)s بينما الصفوف الحالية %(actual)s. "
                "اضغط إعادة المزامنة قبل التفعيل.",
                expected=", ".join(expected_names) or "بدون متغيرات",
                actual=", ".join(actual_names) or "بدون متغيرات",
            )
        return params, ""

    def _send_template(self, record, phone, custom_params):
        # Validate the exact live template first; live validation also refreshes
        # the stored contract. Then rebuild the payload from API names, not from
        # the visible {{1}} aliases.
        if not self._validate_template_live(force=False, raise_error=False):
            return super()._send_template(record, phone, custom_params)

        params, contract_error = self._contract_send_params(record)
        if contract_error:
            self.env["wati.automation.log"].sudo().create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=contract_error,
                )
            )
            return False

        _logger.warning(
            "WATI_TEMPLATE_SEND_CONTRACT rule=%s template=%r param_names=%s count=%s",
            self.id,
            self.template_name,
            [item["name"] for item in params],
            len(params),
        )
        return super()._send_template(record, phone, params)

    @api.model
    def _repair_live_template_contracts(self):
        rules = self.sudo().with_context(active_test=False).search(
            [("template_name", "!=", False)], order="id"
        )
        _logger.warning("WATI_TEMPLATE_CONTRACT_REPAIR_START rules=%s", rules.ids)
        for rule in rules:
            try:
                ok = rule._validate_template_live(force=True, raise_error=False)
                rule.invalidate_recordset(["parameter_ids"])
                rows = rule.parameter_ids.sorted("sequence")
                _logger.warning(
                    "WATI_TEMPLATE_CONTRACT_REPAIR rule=%s active=%s template=%r state=%s slots=%s rows=%s",
                    rule.id,
                    rule.active,
                    rule.template_name,
                    rule.template_contract_state,
                    [
                        (slot.get("token"), slot.get("api_name"))
                        for slot in (rule._contract().get("slots") or [])
                    ],
                    [(row.param_name, row.api_param_name) for row in rows],
                )
                if not ok and rule.template_contract_state == "invalid" and rule.active:
                    # Fail closed: a provably mismatched contract must never keep
                    # running in production. Temporary WATI connectivity errors do
                    # not deactivate rules because their state remains unknown.
                    rule.with_context(
                        wati_contract_internal=True,
                        wati_guard_internal=True,
                    ).write({"active": False})
                    rule._sync_odoo_automation()
                    _logger.error(
                        "WATI_TEMPLATE_CONTRACT_SAFETY_DEACTIVATED rule=%s template=%r reason=%s",
                        rule.id,
                        rule.template_name,
                        rule.template_contract_message,
                    )
            except Exception:
                _logger.exception(
                    "WATI_TEMPLATE_CONTRACT_REPAIR_FAILED rule=%s template=%r",
                    rule.id,
                    rule.template_name,
                )
        _logger.warning("WATI_TEMPLATE_CONTRACT_REPAIR_DONE rules=%s", rules.ids)
        return True


class WatiAutomationParameterTemplateContract(models.Model):
    _inherit = "wati.automation.parameter"

    placeholder_token = fields.Char(
        string="موضع المتغير في الرسالة",
        copy=False,
        help="مثل 1 في {{1}}. يستخدم للمعاينة فقط، وليس بالضرورة اسم WATI API.",
    )
    api_param_name = fields.Char(
        string="اسم المتغير في WATI API",
        copy=False,
        help="الاسم الحقيقي الذي يجب إرساله داخل customParams إلى WATI.",
    )

    @api.depends("sequence", "param_name", "placeholder_token", "api_param_name")
    def _compute_template_variable_label(self):
        for line in self:
            token = (line.placeholder_token or line.param_name or "").strip()
            if not token:
                position = max(1, int((line.sequence or 10) / 10))
                token = str(position)
            line.template_variable_label = "{{%s}}" % token


class WatiAutomationTemplateChoiceContract(models.TransientModel):
    _inherit = "wati.automation.template.choice"

    contract_json = fields.Text(readonly=True)
    template_external_id = fields.Char(readonly=True)

    def action_select(self):
        self.ensure_one()
        rule = self.rule_id
        contract = _loads_contract(self.contract_json)
        if not contract:
            contract = {
                "version": 1,
                "state": "unknown",
                "source": "choice-missing",
                "template_name": self.name,
                "template_id": self.template_external_id or "",
                "language": getattr(self, "language", False) or "",
                "channel": getattr(self, "channel_number", False) or "",
                "body_tokens": _template_body_tokens({"body": self.body or ""}),
                "api_names": [],
                "slots": [
                    {"token": token, "api_name": token}
                    for token in _template_body_tokens({"body": self.body or ""})
                ],
                "message": _("سيتم التحقق من عقد القالب Live قبل التفعيل."),
            }

        rule.parameter_ids.unlink()
        rule.with_context(
            wati_contract_internal=True,
            wati_guard_internal=True,
        ).write(
            {
                "template_name": self.name,
                "template_body": self.body or False,
                "template_language": getattr(self, "language", False) or False,
                "template_channel_number": getattr(self, "channel_number", False) or False,
                "template_external_id": self.template_external_id or contract.get("template_id") or False,
                "template_contract_json": json.dumps(contract, ensure_ascii=False),
                "template_contract_state": contract.get("state") or "unknown",
                "template_contract_message": contract.get("message") or False,
                "template_param_names_json": json.dumps(
                    [slot.get("token") for slot in contract.get("slots") or []],
                    ensure_ascii=False,
                ),
                "template_validation_state": "unverified",
                "template_validation_message": False,
                "template_verified_at": False,
                "preview_text": False,
                "preview_record_name": False,
            }
        )
        rule._apply_template_contract(contract, reason="template_selection_contract")
        rule._auto_map_parameters()

        return {
            "type": "ir.actions.act_window",
            "name": rule.name,
            "res_model": "wati.automation.rule",
            "res_id": rule.id,
            "view_mode": "form",
            "target": "current",
        }
