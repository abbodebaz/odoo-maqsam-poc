import json
import logging

from odoo import api, models


_logger = logging.getLogger(__name__)

_STATUS_RANK = {
    "accepted": 0,
    "queued": 0,
    "pending": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "replied": 4,
}
_FAILED_STATUS_TOKENS = ("fail", "error", "undeliver", "reject", "expired")


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


def _status_rank(value):
    clean = _clean(value).casefold()
    for token, rank in _STATUS_RANK.items():
        if token in clean:
            return rank
    return -1


def _is_failed_status(value):
    clean = _clean(value).casefold()
    return any(token in clean for token in _FAILED_STATUS_TOKENS)


def _payload_source(message):
    try:
        payload = json.loads(message.raw_payload or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    return _clean(payload.get("source")) if isinstance(payload, dict) else ""


def _pick_status(messages):
    """Choose the furthest truthful lifecycle state across duplicate rows."""
    ranked = []
    failed = []
    unknown = []
    for message in messages:
        status = _clean(message.status)
        if not status:
            continue
        rank = _status_rank(status)
        if rank >= 0:
            ranked.append((rank, message.id, status))
        elif _is_failed_status(status):
            failed.append((message.id, status))
        else:
            unknown.append((message.id, status))

    if ranked:
        best = max(ranked)
        if failed and best[0] < 2:
            return max(failed)[1]
        return best[2]
    if failed:
        return max(failed)[1]
    if unknown:
        return max(unknown)[1]
    return ""


def _first_nonempty(messages, field_name):
    for message in messages:
        value = message[field_name]
        if value not in (None, False, ""):
            return value
    return False


def _earliest(messages, field_name):
    values = [message[field_name] for message in messages if message[field_name]]
    return min(values) if values else False


def _latest(messages, field_name):
    values = [message[field_name] for message in messages if message[field_name]]
    return max(values) if values else False


class WatiMessageIdentity(models.Model):
    _inherit = "wati.message"

    def _wati_canonical_score(self):
        self.ensure_one()
        return (
            int(_payload_source(self) == "odoo_session_send"),
            int(bool(_clean(self.local_message_id))),
            int(bool(_clean(self.whatsapp_message_id))),
            -self.id,
        )

    def _wati_merge_identity_group(self):
        """Merge records proven to represent the same logical WhatsApp message."""
        records = self.sudo().exists()
        if len(records) <= 1:
            return records

        whatsapp_ids = {
            _clean(message.whatsapp_message_id)
            for message in records
            if _clean(message.whatsapp_message_id)
        }
        local_ids = {
            _clean(message.local_message_id)
            for message in records
            if _clean(message.local_message_id)
        }
        if len(local_ids) == 1 and len(whatsapp_ids) > 1:
            _logger.warning(
                "WATI_MESSAGE_IDENTITY_CONFLICT local=%s whatsapp=%s ids=%s",
                next(iter(local_ids)),
                sorted(whatsapp_ids),
                records.ids,
            )
            return records

        canonical = max(records, key=lambda message: message._wati_canonical_score())
        duplicates = records - canonical
        ordered = [canonical] + list(duplicates.sorted(key=lambda message: message.id))

        whatsapp_id = _first_nonempty(ordered, "whatsapp_message_id")
        local_id = _first_nonempty(ordered, "local_message_id")
        status = _pick_status(ordered)
        conversation = canonical.conversation_id or _first_nonempty(
            ordered, "conversation_id"
        )

        text_candidates = [
            _clean(message.text) for message in ordered if _clean(message.text)
        ]
        raw_candidates = [
            _clean(message.raw_payload)
            for message in ordered
            if _clean(message.raw_payload)
        ]

        values = {
            "name": whatsapp_id or local_id or canonical.name,
            "whatsapp_message_id": whatsapp_id or False,
            "local_message_id": local_id or False,
            "conversation_id": conversation.id if conversation else False,
            "conversation_uid": _first_nonempty(ordered, "conversation_uid"),
            "ticket_uid": _first_nonempty(ordered, "ticket_uid"),
            "wa_id": _first_nonempty(ordered, "wa_id"),
            "bsuid": _first_nonempty(ordered, "bsuid"),
            "channel_phone_number": _first_nonempty(ordered, "channel_phone_number"),
            "sender_name": _first_nonempty(ordered, "sender_name"),
            "direction": _first_nonempty(ordered, "direction") or canonical.direction,
            "message_type": _first_nonempty(ordered, "message_type") or "text",
            "text": max(text_candidates, key=len) if text_candidates else canonical.text,
            "status": status or canonical.status,
            "operator_name": _first_nonempty(ordered, "operator_name"),
            "operator_email": _first_nonempty(ordered, "operator_email"),
            "received_at": _earliest(ordered, "received_at") or canonical.received_at,
            "accepted_at": _earliest(ordered, "accepted_at"),
            "sent_at": _earliest(ordered, "sent_at"),
            "delivered_at": _earliest(ordered, "delivered_at"),
            "read_at": _earliest(ordered, "read_at"),
            "failed_at": _earliest(ordered, "failed_at"),
            "status_updated_at": _latest(ordered, "status_updated_at"),
            "raw_payload": max(raw_candidates, key=len)
            if raw_candidates
            else canonical.raw_payload,
        }

        events = self.env["wati.webhook.event"].sudo().search(
            [("linked_message_id", "in", duplicates.ids)]
        )
        if events:
            events.write({"linked_message_id": canonical.id})

        canonical.with_context(wati_skip_message_identity=True).write(values)
        duplicates.with_context(wati_skip_message_identity=True).unlink()
        _logger.info(
            "WATI_MESSAGE_IDENTITY_MERGED canonical=%s removed=%s local=%s whatsapp=%s",
            canonical.id,
            duplicates.ids,
            local_id or "",
            whatsapp_id or "",
        )
        return canonical

    def _wati_reconcile_identity(self):
        """Reconcile exact provider/local identities visible in this transaction."""
        records = self.sudo().exists()
        if not records:
            return records

        result = records
        whatsapp_ids = {
            _clean(message.whatsapp_message_id)
            for message in records
            if _clean(message.whatsapp_message_id)
        }
        local_ids = {
            _clean(message.local_message_id)
            for message in records
            if _clean(message.local_message_id)
        }

        for whatsapp_id in whatsapp_ids:
            group = self.sudo().search(
                [("whatsapp_message_id", "=", whatsapp_id)], order="id asc"
            )
            if len(group) > 1:
                result = group._wati_merge_identity_group()

        for local_id in local_ids:
            group = self.sudo().search(
                [("local_message_id", "=", local_id)], order="id asc"
            )
            provider_ids = {
                _clean(message.whatsapp_message_id)
                for message in group
                if _clean(message.whatsapp_message_id)
            }
            if len(group) > 1 and len(provider_ids) <= 1:
                result = group._wati_merge_identity_group()

        return result.exists()

    def write(self, vals):
        result = super().write(vals)
        if (
            not self.env.context.get("wati_skip_message_identity")
            and any(key in vals for key in ("whatsapp_message_id", "local_message_id"))
        ):
            self._wati_reconcile_identity()
        return result

    @api.model
    def _wati_repair_duplicate_identities(self):
        """Fast upgrade repair for Odoo-originated sends with a local identity.

        Historical provider-only callback duplicates can be numerous and must not make
        application startup depend on a large maintenance sweep. Runtime reconciliation
        still collapses exact WhatsApp identities whenever new lifecycle callbacks arrive.
        The startup repair therefore targets only duplicate localMessageId groups, which
        is the authoritative bridge for Mini/Full Inbox sends initiated by this Odoo.
        """
        count_before = self.sudo().search_count([])
        self.env.cr.execute(
            """
            SELECT local_message_id
              FROM wati_message
             WHERE COALESCE(local_message_id, '') <> ''
             GROUP BY local_message_id
            HAVING COUNT(*) > 1
             ORDER BY MIN(id)
            """
        )
        local_ids = [row[0] for row in self.env.cr.fetchall()]
        repaired = conflicts = 0

        for local_id in local_ids:
            group = self.sudo().search(
                [("local_message_id", "=", local_id)], order="id asc"
            )
            provider_ids = {
                _clean(message.whatsapp_message_id)
                for message in group
                if _clean(message.whatsapp_message_id)
            }
            if len(provider_ids) > 1:
                conflicts += 1
                _logger.warning(
                    "WATI_MESSAGE_IDENTITY_REPAIR_SKIP local=%s whatsapp=%s ids=%s",
                    local_id,
                    sorted(provider_ids),
                    group.ids,
                )
                continue
            if len(group) > 1:
                before = len(group)
                merged = group._wati_merge_identity_group()
                repaired += max(0, before - len(merged))

        count_after = self.sudo().search_count([])
        _logger.warning(
            "WATI_MESSAGE_IDENTITY_REPAIR mode=local_message_id groups=%s repaired=%s "
            "conflicts=%s before=%s after=%s",
            len(local_ids),
            repaired,
            conflicts,
            count_before,
            count_after,
        )
        return True


class WatiWebhookEventMessageIdentity(models.Model):
    _inherit = "wati.webhook.event"

    @api.model
    def ingest(self, payload):
        result = super().ingest(payload)
        if not isinstance(payload, dict):
            return result

        Message = self.env["wati.message"].sudo()
        whatsapp_id = _clean(payload.get("whatsappMessageId"))
        local_id = _clean(payload.get("localMessageId"))
        candidates = Message.browse()
        if whatsapp_id:
            candidates |= Message.search([("whatsapp_message_id", "=", whatsapp_id)])
        if local_id:
            candidates |= Message.search([("local_message_id", "=", local_id)])
        if candidates:
            candidates._wati_reconcile_identity()
        return result
