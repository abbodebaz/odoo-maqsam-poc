from odoo import http
from odoo.http import request

from odoo.addons.wati_connector.controllers.customer_context import (
    WatiCustomerContextController,
    _conversation_from_request,
    _conversation_partner,
    _partner_phone_value,
    _record_form_url,
)


class WatiCustomerContextCrmController(WatiCustomerContextController):
    """CRM-specific customer context kept inside the optional CRM addon."""

    def _context_extensions(self, conversation, partner):
        payload = dict(super()._context_extensions(conversation, partner))
        opportunities = request.env["crm.lead"].browse()
        if partner:
            opportunities = request.env["crm.lead"].search(
                [("partner_id", "=", partner.id), ("type", "=", "opportunity")],
                order="write_date desc, id desc",
                limit=20,
            )
        payload["opportunities"] = [
            {
                "id": lead.id,
                "name": lead.name,
                "stage_name": lead.stage_id.name if lead.stage_id else "",
                "user_name": lead.user_id.name if lead.user_id else "",
                "expected_revenue": lead.expected_revenue or 0.0,
                "url": _record_form_url("crm.lead", lead.id),
            }
            for lead in opportunities
        ]
        return payload

    @http.route()
    def customer_context(self, conversation_id=None, **kwargs):
        return super().customer_context(conversation_id=conversation_id, **kwargs)

    @http.route(
        "/wati/inbox/opportunity/create",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def create_opportunity(
        self,
        conversation_id=None,
        name=None,
        expected_revenue=None,
        description=None,
        **kwargs,
    ):
        conversation = _conversation_from_request(conversation_id)
        if not conversation:
            return request.make_json_response(
                {"ok": False, "message": "The conversation does not exist."},
                status=404,
            )

        partner = _conversation_partner(conversation, persist=True)
        if not partner:
            return request.make_json_response(
                {
                    "ok": False,
                    "message": "Create or link an Odoo customer before creating an opportunity.",
                },
                status=409,
            )

        try:
            revenue = float(expected_revenue or 0)
        except (TypeError, ValueError):
            revenue = 0.0

        lead_name = (name or "").strip() or f"WhatsApp Opportunity - {partner.display_name}"
        lead_model = request.env["crm.lead"]
        values = {
            "name": lead_name,
            "type": "opportunity",
            "partner_id": partner.id,
            "user_id": request.env.user.id,
            "expected_revenue": max(0.0, revenue),
        }
        if "phone" in lead_model._fields:
            values["phone"] = _partner_phone_value(partner) or conversation.wa_id or ""
        if description and "description" in lead_model._fields:
            values["description"] = description.strip()

        lead = lead_model.create(values)
        return request.make_json_response(
            {
                "ok": True,
                "message": f"Opportunity {lead.name} created ✅",
                "opportunity_id": lead.id,
                "opportunity_name": lead.name,
                "opportunity_url": _record_form_url("crm.lead", lead.id),
            },
            status=200,
        )
