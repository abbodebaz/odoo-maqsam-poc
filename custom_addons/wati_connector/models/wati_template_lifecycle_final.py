import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.template_catalog import clean, find_template_list, normalize_template


_logger = logging.getLogger(__name__)


_LANGUAGE_NAME_ALIASES = {
    "arabic": "ar",
    "العربية": "ar",
    "عربي": "ar",
    "english": "en",
    "الإنجليزية": "en",
    "انجليزي": "en",
    "french": "fr",
    "spanish": "es",
}

_REJECTION_KEYS = (
    "rejectionReason",
    "rejectedReason",
    "rejection_reason",
    "reason",
    "errorMessage",
    "error_message",
)


class WatiTemplateLifecycleFinal(models.Model):
    """Final provider-truth layer for the WhatsApp template lifecycle.

    Provider-created templates must never get stuck because a generic bulk
    catalogue endpoint is stale or because WATI represents a language as
    ``Arabic``/``ar-SA`` while the Odoo draft stores ``ar``. Lifecycle reads use
    WATI v2's exact-name filter first, then fall back to the existing v1 bulk
    catalogue. A small poller complements webhooks so approval/rejection state is
    eventually correct even when a template webhook is delayed or not enabled.
    """

    _inherit = "wati.template"

    @api.model
    def _language_match_key(self, value):
        raw = clean(value).casefold().replace("_", "-")
        if not raw:
            return ""
        return _LANGUAGE_NAME_ALIASES.get(raw, raw)

    @api.model
    def _languages_equivalent(self, left, right):
        left_key = self._language_match_key(left)
        right_key = self._language_match_key(right)
        if not left_key or not right_key:
            return False
        if left_key == right_key:
            return True
        left_base = left_key.split("-", 1)[0]
        right_base = right_key.split("-", 1)[0]
        return left_base == right_base and (
            "-" not in left_key or "-" not in right_key
        )

    @api.model
    def _rejection_reason_from_raw(self, raw):
        if not isinstance(raw, dict):
            return ""

        candidates = [raw]
        for key in ("result", "data", "template", "messageTemplate"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)

        for candidate in candidates:
            for key in _REJECTION_KEYS:
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    for nested_key in (
                        "message",
                        "reason",
                        "text",
                        "description",
                        "details",
                    ):
                        nested = value.get(nested_key)
                        if isinstance(nested, str) and nested.strip():
                            return nested.strip()
        return ""

    def _remote_identity_match(self, normalized):
        self.ensure_one()
        if not normalized:
            return False
        if clean(normalized.get("name")).casefold() != clean(self.name).casefold():
            return False
        if normalized.get("_language_missing"):
            return True
        return self._languages_equivalent(
            normalized.get("language"),
            self.language,
        )

    def _normalize_lifecycle_item(self, item):
        self.ensure_one()
        normalized = normalize_template(item)
        if not normalized:
            return None
        raw_language_present = False
        if isinstance(item, dict):
            raw_language_present = any(
                item.get(key) not in (None, False, "", {})
                for key in ("language", "languageCode", "locale")
            )
        normalized["_language_missing"] = not raw_language_present
        normalized["rejection_reason"] = self._rejection_reason_from_raw(item)
        return normalized

    def _fetch_exact_remote_submission_v2(self):
        self.ensure_one()
        client = WatiClient(self.env)
        for page_number in range(1, 4):
            response = client.get(
                "api/v2/getMessageTemplates",
                params={
                    "pageSize": 100,
                    "pageNumber": page_number,
                    "name": clean(self.name),
                },
                timeout=25,
            )
            try:
                payload = response.json()
            except ValueError as exc:
                raise UserError(
                    _("WATI أعاد استجابة غير مفهومة أثناء التحقق من حالة القالب.")
                ) from exc
            items = find_template_list(payload)
            if not items:
                break
            for item in items:
                normalized = self._normalize_lifecycle_item(item)
                if self._remote_identity_match(normalized):
                    return normalized
            if len(items) < 100:
                break
        return None

    def _find_remote_submission(self):
        self.ensure_one()
        try:
            normalized = self._fetch_exact_remote_submission_v2()
            if normalized:
                return normalized
        except (WatiConfigurationError, WatiRequestError, UserError) as exc:
            _logger.warning(
                "WATI_TEMPLATE_V2_LOOKUP_FALLBACK id=%s name=%r error=%s",
                self.id,
                self.name,
                clean(getattr(exc, "response_text", "") or str(exc))[:500],
            )

        # Backward-compatible fallback for WATI accounts where v2 is unavailable.
        for item in self._fetch_remote_templates():
            normalized = self._normalize_lifecycle_item(item)
            if self._remote_identity_match(normalized):
                return normalized
        return None

    @api.model
    def _remote_values(self, normalized, now=None):
        values = super()._remote_values(normalized, now=now)
        status = normalized.get("status")
        reason = clean(
            normalized.get("rejection_reason")
            or self._rejection_reason_from_raw(normalized.get("raw"))
        )
        if status == "rejected":
            values["rejection_reason"] = reason or _(
                "رفض Meta القالب، لكن WATI لم يُرجع سبب الرفض عبر واجهة API الحالية."
            )
        elif status in {
            "draft",
            "pending",
            "pending_internal",
            "approved",
            "paused",
            "disabled",
            "deleted",
        }:
            values["rejection_reason"] = False
        return values

    def _apply_lifecycle_remote(self, normalized, *, reason="manual_refresh"):
        self.ensure_one()
        now = fields.Datetime.now()
        values = self._remote_values(normalized, now=now)
        values["last_error"] = False
        self.sudo().write(values)
        self._sync_readonly_variables(normalized.get("custom_params") or [])
        _logger.warning(
            "WATI_TEMPLATE_FINAL_SYNC id=%s name=%r reason=%s remote_language=%r status=%r rejection=%r wati_id=%r meta_id=%r",
            self.id,
            self.name,
            reason,
            normalized.get("language"),
            normalized.get("status"),
            clean(self.rejection_reason)[:300],
            self.wati_template_id,
            self.meta_template_id,
        )
        return True

    def _apply_verified_remote_template(self, normalized):
        self.ensure_one()
        return self._apply_lifecycle_remote(normalized, reason="submission_verify")

    def _refresh_lifecycle_from_provider(self, *, reason="manual_refresh"):
        self.ensure_one()
        normalized = self._find_remote_submission()
        if not normalized:
            self.sudo().write(
                {
                    "last_synced_at": fields.Datetime.now(),
                    "last_error": _("لم يظهر هذا القالب في نتيجة WATI الحالية."),
                }
            )
            _logger.warning(
                "WATI_TEMPLATE_FINAL_SYNC_MISSING id=%s name=%r language=%r reason=%s",
                self.id,
                self.name,
                self.language,
                reason,
            )
            return False
        return self._apply_lifecycle_remote(normalized, reason=reason)

    def action_refresh_status(self):
        for record in self:
            try:
                record._refresh_lifecycle_from_provider(reason="manual_refresh")
            except (WatiConfigurationError, WatiRequestError, UserError) as exc:
                detail = clean(getattr(exc, "response_text", "") or str(exc))[:1200]
                record.sudo().write(
                    {
                        "last_synced_at": fields.Datetime.now(),
                        "last_error": detail,
                    }
                )

        found = self.filtered(lambda record: not record.last_error)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تحديث حالة القوالب"),
                "message": _("تم تحديث %s من %s قالبًا من WATI.")
                % (len(found), len(self)),
                "type": "success" if found else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    @api.model
    def _cron_refresh_pending_template_lifecycle(self):
        records = self.sudo().search(
            [
                ("source", "=", "odoo"),
                ("status", "in", ["pending", "pending_internal"]),
                ("active", "=", True),
            ],
            order="submitted_at asc, id asc",
            limit=100,
        )
        updated = 0
        for record in records:
            try:
                if record._refresh_lifecycle_from_provider(reason="poller"):
                    updated += 1
            except Exception:
                _logger.exception(
                    "WATI_TEMPLATE_POLLER_FAILED id=%s name=%r",
                    record.id,
                    record.name,
                )
        if records:
            _logger.warning(
                "WATI_TEMPLATE_POLLER_DONE checked=%s updated=%s",
                len(records),
                updated,
            )
        return True

    @api.model
    def _repair_pending_template_lifecycle(self):
        records = self.sudo().search(
            [
                ("source", "=", "odoo"),
                ("status", "in", ["pending", "pending_internal"]),
            ],
            order="id asc",
        )
        updated = 0
        for record in records:
            try:
                if record._refresh_lifecycle_from_provider(reason="module_upgrade"):
                    updated += 1
            except Exception:
                _logger.exception(
                    "WATI_TEMPLATE_FINAL_REPAIR_FAILED id=%s name=%r",
                    record.id,
                    record.name,
                )
        _logger.warning(
            "WATI_TEMPLATE_FINAL_REPAIR_DONE checked=%s updated=%s ids=%s",
            len(records),
            updated,
            records.ids,
        )
        return True


class WatiTemplateWebhookFinal(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def _canonical_template_event(self, value):
        raw = clean(value)
        key = raw.casefold().replace("_", "").replace("-", "")
        return {
            "templatereviewed": "templateReviewed",
            "templatequalityupdated": "templateQualityUpdated",
            "templatecategoryupdated": "templateCategoryUpdated",
        }.get(key, "")

    @api.model
    def ingest(self, payload):
        # Existing handler covers the documented root payload. This additional
        # pass catches providers that wrap the event in data/payload/event/body
        # or vary only the eventType casing/separators.
        if isinstance(payload, dict):
            candidates = [payload]
            for key in ("data", "payload", "event", "body"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    candidates.append(nested)
            for candidate in candidates:
                canonical = self._canonical_template_event(candidate.get("eventType"))
                if not canonical:
                    continue
                if candidate is payload and candidate.get("eventType") == canonical:
                    break
                normalized = dict(candidate)
                normalized["eventType"] = canonical
                if self.env["wati.template"].sudo().apply_template_webhook(normalized):
                    _logger.warning(
                        "WATI_TEMPLATE_WEBHOOK_NORMALIZED event=%s template=%r",
                        canonical,
                        clean(normalized.get("templateName")),
                    )
                    break
        return super().ingest(payload)
