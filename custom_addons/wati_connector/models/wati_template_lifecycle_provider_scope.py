import json
import logging

from odoo import api, models

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.template_catalog import clean, find_template_list, normalize_status


_logger = logging.getLogger(__name__)


class WatiTemplateLifecycleProviderScope(models.Model):
    """Resolve template state from the provider scope and webhook audit trail.

    Some WATI workspaces expose a template in the dashboard before (or without)
    returning it from the unscoped catalogue. Prefer the exact WABA/channel when
    identifiers are known, and use Odoo's immutable webhook audit as an
    independent provider-truth fallback before falling back to the generic
    catalogue implemented by the previous lifecycle layer.
    """

    _inherit = "wati.template"

    def _safe_remote_summary(self, item):
        if not isinstance(item, dict):
            return {}
        summary = {}
        for key in (
            "elementName",
            "templateName",
            "name",
            "language",
            "languageCode",
            "status",
            "approvalStatus",
            "templateStatus",
            "newTemplateStatus",
            "templateId",
            "watiTemplateId",
            "wabaId",
            "channelPhoneNumber",
            "rejectionReason",
            "reason",
            "errorMessage",
        ):
            value = item.get(key)
            if value not in (None, False, "", {}, []):
                summary[key] = value
        return summary

    def _scoped_v2_candidates(self):
        self.ensure_one()
        client = WatiClient(self.env)
        base = {
            "pageSize": 100,
            "pageNumber": 1,
            "name": clean(self.name),
        }
        variants = []
        if clean(self.waba_id):
            scoped = dict(base)
            scoped["wabaId"] = clean(self.waba_id)
            variants.append(scoped)
        variants.append(base)

        seen = set()
        for params in variants:
            key = tuple(sorted(params.items()))
            if key in seen:
                continue
            seen.add(key)
            response = client.get(
                "api/v2/getMessageTemplates",
                params=params,
                timeout=25,
            )
            payload = response.json()
            items = find_template_list(payload)
            _logger.warning(
                "WATI_TEMPLATE_SCOPE_V2 id=%s name=%r waba=%r count=%s candidates=%s",
                self.id,
                self.name,
                params.get("wabaId"),
                len(items),
                [self._safe_remote_summary(item) for item in items[:5]],
            )
            for item in items:
                normalized = self._normalize_lifecycle_item(item)
                if self._remote_identity_match(normalized):
                    return normalized
        return None

    def _scoped_v1_candidates(self):
        self.ensure_one()
        client = WatiClient(self.env)
        channel = clean(self.channel_phone_number or client.config.channel_number)
        if not channel:
            return None

        for page_number in range(1, 6):
            response = client.get(
                "api/v1/getMessageTemplates",
                params={
                    "pageSize": 200,
                    "pageNumber": page_number,
                    "channelPhoneNumber": channel,
                },
                timeout=25,
            )
            payload = response.json()
            items = find_template_list(payload)
            if page_number == 1:
                exact_named = []
                for item in items:
                    normalized = self._normalize_lifecycle_item(item)
                    if normalized and clean(normalized.get("name")).casefold() == clean(self.name).casefold():
                        exact_named.append(self._safe_remote_summary(item))
                _logger.warning(
                    "WATI_TEMPLATE_SCOPE_V1 id=%s name=%r channel=%r count=%s exact_named=%s",
                    self.id,
                    self.name,
                    channel,
                    len(items),
                    exact_named[:5],
                )
            if not items:
                break
            for item in items:
                normalized = self._normalize_lifecycle_item(item)
                if self._remote_identity_match(normalized):
                    return normalized
            if len(items) < 200:
                break
        return None

    @api.model
    def _walk_payload_dicts(self, value, depth=0):
        if depth > 6:
            return []
        result = []
        if isinstance(value, dict):
            result.append(value)
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    result.extend(self._walk_payload_dicts(nested, depth + 1))
        elif isinstance(value, list):
            for nested in value[:100]:
                if isinstance(nested, (dict, list)):
                    result.extend(self._walk_payload_dicts(nested, depth + 1))
        return result

    def _find_lifecycle_from_webhook_audit(self):
        self.ensure_one()
        events = self.env["wati.webhook.event"].sudo().search(
            [("payload", "ilike", clean(self.name))],
            order="received_at desc, id desc",
            limit=100,
        )
        for event in events:
            try:
                payload = json.loads(event.payload or "{}")
            except (TypeError, ValueError):
                continue
            for node in self._walk_payload_dicts(payload):
                remote_name = clean(
                    node.get("templateName")
                    or node.get("elementName")
                    or node.get("template_name")
                )
                if remote_name.casefold() != clean(self.name).casefold():
                    continue
                raw_status = (
                    node.get("newTemplateStatus")
                    if node.get("newTemplateStatus") is not None
                    else node.get("templateStatus", node.get("approvalStatus"))
                )
                if normalize_status(raw_status) == "unknown":
                    continue

                synthetic = dict(node)
                synthetic["elementName"] = self.name
                synthetic["status"] = raw_status
                synthetic.setdefault("language", self.language)
                synthetic.setdefault("category", self.category)
                synthetic.setdefault("subCategory", self.sub_category or "STANDARD")
                synthetic.setdefault("body", self.body or "—")
                synthetic.setdefault(
                    "customParams",
                    [{"name": row.name} for row in self.variable_ids if row.name],
                )
                normalized = self._normalize_lifecycle_item(synthetic)
                if not normalized or not self._remote_identity_match(normalized):
                    continue
                _logger.warning(
                    "WATI_TEMPLATE_WEBHOOK_AUDIT_HIT id=%s name=%r event_id=%s event_type=%r summary=%s",
                    self.id,
                    self.name,
                    event.id,
                    event.event_type,
                    self._safe_remote_summary(node),
                )
                return normalized
        _logger.warning(
            "WATI_TEMPLATE_WEBHOOK_AUDIT_MISS id=%s name=%r events=%s",
            self.id,
            self.name,
            len(events),
        )
        return None

    def _find_remote_submission(self):
        self.ensure_one()
        for finder_name in (
            "_scoped_v2_candidates",
            "_scoped_v1_candidates",
            "_find_lifecycle_from_webhook_audit",
        ):
            try:
                normalized = getattr(self, finder_name)()
                if normalized:
                    return normalized
            except (WatiConfigurationError, WatiRequestError, ValueError) as exc:
                _logger.warning(
                    "WATI_TEMPLATE_SCOPE_LOOKUP_FAILED id=%s name=%r finder=%s error=%s",
                    self.id,
                    self.name,
                    finder_name,
                    clean(getattr(exc, "response_text", "") or str(exc))[:800],
                )
        return super()._find_remote_submission()

    @api.model
    def _repair_pending_template_lifecycle(self):
        records = self.sudo().search(
            [
                ("source", "=", "odoo"),
                ("status", "in", ["pending", "pending_internal"]),
            ],
            order="id asc",
        )
        for record in records:
            response_summary = {}
            try:
                payload = json.loads(record.provider_response or "{}")
            except (TypeError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                response_summary.update(record._safe_remote_summary(payload))
                nested = payload.get("result")
                if isinstance(nested, dict):
                    response_summary["result"] = record._safe_remote_summary(nested)
            _logger.warning(
                "WATI_TEMPLATE_SCOPE_REPAIR_CONTEXT id=%s name=%r language=%r wati_id=%r meta_id=%r waba=%r channel=%r create_response=%s",
                record.id,
                record.name,
                record.language,
                record.wati_template_id,
                record.meta_template_id,
                record.waba_id,
                record.channel_phone_number,
                response_summary,
            )
        return super()._repair_pending_template_lifecycle()
