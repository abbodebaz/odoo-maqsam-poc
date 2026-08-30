from odoo import fields, http
from odoo.http import request

from .main import _find_partner_by_wa_id, _partner_phone_value, _partner_url


def _record_form_url(model_name, record_id):
    if not record_id:
        return ""
    return f"/web#id={int(record_id)}&model={model_name}&view_type=form"


def _conversation_from_request(conversation_id):
    try:
        conversation_id = int(conversation_id or 0)
    except (TypeError, ValueError):
        conversation_id = 0
    return request.env["wati.conversation"].browse(conversation_id).exists()


def _conversation_partner(conversation, persist=False):
    if not conversation:
        return request.env["res.partner"].browse()
    partner = conversation.partner_id or _find_partner_by_wa_id(conversation.wa_id)
    if partner and persist and conversation.partner_id != partner:
        conversation.write({"partner_id": partner.id})
    return partner


def _ticket_status_label(ticket):
    selection = dict(ticket._fields["status"].selection)
    return selection.get(ticket.status, ticket.status or "")


class WatiCustomerContextController(http.Controller):

    @http.route(
        "/wati/inbox/customer-context",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def customer_context(self, conversation_id=None, **kwargs):
        conversation = _conversation_from_request(conversation_id)
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        partner = _conversation_partner(conversation, persist=False)

        tickets = request.env["wati.support.ticket"].search(
            [("conversation_id", "=", conversation.id)],
            order="create_date desc, id desc",
            limit=20,
        )

        opportunities = request.env["crm.lead"].browse()
        if partner:
            opportunities = request.env["crm.lead"].search(
                [("partner_id", "=", partner.id), ("type", "=", "opportunity")],
                order="write_date desc, id desc",
                limit=20,
            )

        partner_payload = False
        if partner:
            partner_payload = {
                "id": partner.id,
                "name": partner.display_name or partner.name or "عميل Odoo",
                "phone": _partner_phone_value(partner) or "",
                "email": partner.email or "",
                "url": _partner_url(partner),
            }

        return request.make_json_response(
            {
                "ok": True,
                "conversation": {
                    "id": conversation.id,
                    "name": conversation.name or conversation.sender_name or conversation.wa_id or "WhatsApp",
                    "wa_id": conversation.wa_id or "",
                },
                "partner": partner_payload,
                "tickets": [
                    {
                        "id": ticket.id,
                        "name": ticket.name,
                        "subject": ticket.subject,
                        "status": ticket.status,
                        "status_label": _ticket_status_label(ticket),
                        "priority": ticket.priority,
                        "user_name": ticket.user_id.name if ticket.user_id else "",
                        "created_at": fields.Datetime.to_string(ticket.create_date) if ticket.create_date else "",
                        "url": _record_form_url("wati.support.ticket", ticket.id),
                    }
                    for ticket in tickets
                ],
                "opportunities": [
                    {
                        "id": lead.id,
                        "name": lead.name,
                        "stage_name": lead.stage_id.name if lead.stage_id else "",
                        "user_name": lead.user_id.name if lead.user_id else "",
                        "expected_revenue": lead.expected_revenue or 0.0,
                        "url": _record_form_url("crm.lead", lead.id),
                    }
                    for lead in opportunities
                ],
            },
            status=200,
        )

    @http.route(
        "/wati/inbox/customer/create",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def create_customer(self, conversation_id=None, name=None, **kwargs):
        conversation = _conversation_from_request(conversation_id)
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        partner = _conversation_partner(conversation, persist=True)
        if partner:
            return request.make_json_response(
                {
                    "ok": True,
                    "message": "المحادثة مرتبطة بعميل Odoo بالفعل.",
                    "partner_id": partner.id,
                    "partner_name": partner.display_name,
                    "partner_url": _partner_url(partner),
                },
                status=200,
            )

        clean_name = (name or conversation.sender_name or conversation.name or "").strip()
        if not clean_name or clean_name.lower() == "whatsapp":
            clean_name = conversation.wa_id or "عميل WhatsApp"

        partner_model = request.env["res.partner"]
        values = {"name": clean_name}
        phone_value = (conversation.wa_id or "").strip()
        if phone_value:
            if "mobile" in partner_model._fields:
                values["mobile"] = phone_value
            elif "phone" in partner_model._fields:
                values["phone"] = phone_value

        partner = partner_model.create(values)
        conversation.write({"partner_id": partner.id})

        return request.make_json_response(
            {
                "ok": True,
                "message": f"تم إنشاء العميل {partner.display_name} ✅",
                "partner_id": partner.id,
                "partner_name": partner.display_name,
                "partner_url": _partner_url(partner),
            },
            status=200,
        )

    @http.route(
        "/wati/inbox/ticket/create",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def create_ticket(self, conversation_id=None, subject=None, description=None, priority=None, **kwargs):
        conversation = _conversation_from_request(conversation_id)
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        partner = _conversation_partner(conversation, persist=True)
        if not partner:
            return request.make_json_response(
                {"ok": False, "message": "أنشئ العميل أو اربط المحادثة بعميل Odoo أولًا."},
                status=409,
            )

        clean_subject = (subject or "").strip() or f"WhatsApp - {partner.display_name}"
        clean_priority = str(priority or "0")
        if clean_priority not in ("0", "1", "2"):
            clean_priority = "0"

        ticket = request.env["wati.support.ticket"].create(
            {
                "subject": clean_subject,
                "description": (description or "").strip(),
                "partner_id": partner.id,
                "conversation_id": conversation.id,
                "user_id": request.env.user.id,
                "priority": clean_priority,
            }
        )

        return request.make_json_response(
            {
                "ok": True,
                "message": f"تم إنشاء التذكرة {ticket.name} ✅",
                "ticket_id": ticket.id,
                "ticket_name": ticket.name,
                "ticket_url": _record_form_url("wati.support.ticket", ticket.id),
            },
            status=200,
        )

    @http.route(
        "/wati/inbox/opportunity/create",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def create_opportunity(self, conversation_id=None, name=None, expected_revenue=None, description=None, **kwargs):
        conversation = _conversation_from_request(conversation_id)
        if not conversation:
            return request.make_json_response({"ok": False, "message": "المحادثة غير موجودة."}, status=404)

        partner = _conversation_partner(conversation, persist=True)
        if not partner:
            return request.make_json_response(
                {"ok": False, "message": "أنشئ العميل أو اربط المحادثة بعميل Odoo أولًا."},
                status=409,
            )

        try:
            revenue = float(expected_revenue or 0)
        except (TypeError, ValueError):
            revenue = 0.0

        lead_name = (name or "").strip() or f"فرصة WhatsApp - {partner.display_name}"
        values = {
            "name": lead_name,
            "type": "opportunity",
            "partner_id": partner.id,
            "user_id": request.env.user.id,
            "expected_revenue": max(0.0, revenue),
        }
        if "phone" in request.env["crm.lead"]._fields:
            values["phone"] = _partner_phone_value(partner) or conversation.wa_id or ""
        if description and "description" in request.env["crm.lead"]._fields:
            values["description"] = description.strip()

        lead = request.env["crm.lead"].create(values)

        return request.make_json_response(
            {
                "ok": True,
                "message": f"تم إنشاء فرصة البيع {lead.name} ✅",
                "opportunity_id": lead.id,
                "opportunity_name": lead.name,
                "opportunity_url": _record_form_url("crm.lead", lead.id),
            },
            status=200,
        )
