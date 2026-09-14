import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BaytAlebaaTestResult(models.Model):
    _name = "bayt.alebaa.test.result"
    _description = "Bayt Alebaa Simulator Test Result"
    _order = "create_date desc, id desc"

    scenario = fields.Char(required=True)
    model_name = fields.Char(required=True)
    record_ref = fields.Char()
    status = fields.Selection([("pass", "Pass"), ("fail", "Fail"), ("info", "Info")], required=True, default="info")
    message = fields.Text()
    payload = fields.Text()


class BaytAlebaaMockMessage(models.Model):
    _name = "bayt.alebaa.mock.message"
    _description = "Mock WATI Message"
    _order = "create_date desc, id desc"

    recipient = fields.Char(required=True)
    template_name = fields.Char()
    source_model = fields.Char()
    source_record_id = fields.Integer()
    trigger = fields.Char()
    payload = fields.Text()
    status = fields.Selection([("would_send", "Would Send"), ("blocked", "Blocked")], default="would_send", required=True)


class BaytAlebaaSimulator(models.Model):
    _name = "bayt.alebaa.simulator"
    _description = "Bayt Alebaa WATI Simulator"

    name = fields.Char(default="Bayt Alebaa QA Lab", required=True)
    mock_wati = fields.Boolean(default=True, string="Mock WATI Mode")
    last_run_at = fields.Datetime(readonly=True)
    notes = fields.Text(default="Use this lab to reproduce Bayt Alebaa model/state transitions without touching the real database.")
    result_count = fields.Integer(compute="_compute_counts")
    mock_message_count = fields.Integer(compute="_compute_counts")

    @api.depends()
    def _compute_counts(self):
        Result = self.env["bayt.alebaa.test.result"]
        Mock = self.env["bayt.alebaa.mock.message"]
        result_count = Result.search_count([])
        mock_count = Mock.search_count([])
        for rec in self:
            rec.result_count = result_count
            rec.mock_message_count = mock_count

    def _log(self, scenario, model_name, status="pass", record=None, message=None, payload=None):
        return self.env["bayt.alebaa.test.result"].create({
            "scenario": scenario,
            "model_name": model_name,
            "record_ref": record and (record.display_name or str(record.id)) or False,
            "status": status,
            "message": message or False,
            "payload": payload and json.dumps(payload, ensure_ascii=False, default=str, indent=2) or False,
        })

    def _attempt(self, scenario, model_name, callback):
        try:
            with self.env.cr.savepoint():
                record, payload = callback()
        except Exception as exc:  # QA lab intentionally records every failure independently.
            _logger.exception("Bayt Alebaa simulator scenario failed: %s", scenario)
            self._log(scenario, model_name, "fail", message=str(exc))
            return False
        self._log(scenario, model_name, "pass", record=record, payload=payload)
        return record

    def _base_partner(self):
        partner = self.env["res.partner"].search([("ref", "=", "SIM-CUST-001")], limit=1)
        if not partner:
            partner = self.env["res.partner"].create({
                "name": "عميل محاكي بيت الإباء",
                "ref": "SIM-CUST-001",
                "phone": "+966500009606",
                "mobile": "+966500009606",
                "email": "simulator@example.com",
                "city": "جدة",
                "lang": "ar_001" if "ar_001" in self.env["res.lang"].get_installed() else "en_US",
                "x_sap_customer_no": "0010453784",
            })
        return partner

    def _product(self):
        product = self.env["product.product"].search([("default_code", "=", "SIM-KITCHEN")], limit=1)
        if not product:
            product = self.env["product.product"].create({
                "name": "مطبخ-kitchen (Simulator)",
                "default_code": "SIM-KITCHEN",
                "list_price": 1000.0,
                "standard_price": 600.0,
                "purchase_ok": True,
                "sale_ok": True,
            })
        return product

    def action_seed_all(self):
        self.ensure_one()
        partner = self._base_partner()
        product = self._product()

        lead = self._attempt("CRM Lead created", "crm.lead", lambda: self._create_lead(partner))
        sale = self._attempt("Sales Order created", "sale.order", lambda: self._create_sale(partner, product, lead))
        purchase = self._attempt("Purchase RFQ created", "purchase.order", lambda: self._create_purchase(product, sale))
        invoice = self._attempt("Customer Invoice created", "account.move", lambda: self._create_invoice(partner, product))
        payment = self._attempt("Customer Payment created", "account.payment", lambda: self._create_payment(partner, sale))
        picking = self._attempt("Delivery Order created", "stock.picking", lambda: self._create_delivery(partner, sale, product))
        mrp = self._attempt("Manufacturing Order created", "mrp.production", lambda: self._create_mrp(product, sale))
        task = self._attempt("Project Task created", "project.task", lambda: self._create_task(partner))
        case = self._attempt("Operation Case created", "operations.operation.case", lambda: self._create_operation_case(partner, invoice, task))
        workflow = self._attempt("Workflow Instance created", "operations.workflow.instance", lambda: self._create_workflow(case, invoice)) if case else False
        answer = self._attempt("Operation Question Answer created", "operations.question.case.answer", lambda: self._create_question_answer(case)) if case else False
        decor = self._attempt("Decor Measurement Form created", "hcos.task.form.decor.measurement", lambda: self._create_decor(partner, task)) if task else False
        install = self._attempt("Installation Form created", "hcos.task.form.installation", lambda: self._create_installation(partner, task)) if task else False
        ticket = self._attempt("Helpdesk Ticket created", "helpdesk.ticket", lambda: self._create_helpdesk(partner, case, task))
        appointment = self._attempt("Appointment Type created", "appointment.type", lambda: self._create_appointment_type())
        event = self._attempt("Appointment Booking created", "calendar.event", lambda: self._create_calendar_event(partner, appointment)) if appointment else False

        self.last_run_at = fields.Datetime.now()
        self._create_mock_messages([lead, sale, purchase, invoice, payment, picking, mrp, task, case, workflow, answer, decor, install, ticket, appointment, event], partner)
        return self.action_open_results()

    def _create_lead(self, partner):
        vals = {
            "name": "مشروع مول جدة - Simulator",
            "partner_id": partner.id,
            "phone": partner.phone,
            "email_from": partner.email,
            "type": "opportunity",
            "expected_revenue": 10000,
            "project_type": "new_kitchen",
            "approximate_budget": 25000,
            "kitchen_reception_visible": True,
        }
        rec = self.env["crm.lead"].create(vals)
        return rec, vals

    def _create_sale(self, partner, product, lead):
        vals = {
            "partner_id": partner.id,
            "opportunity_id": lead.id if lead else False,
            "order_line": [(0, 0, {"product_id": product.id, "product_uom_qty": 1, "price_unit": 1000})],
        }
        rec = self.env["sale.order"].create(vals)
        return rec, {"partner": partner.display_name, "state": rec.state, "amount_total": rec.amount_total}

    def _create_purchase(self, product, sale):
        vendor = self.env["res.partner"].search([("ref", "=", "SIM-VENDOR-001")], limit=1)
        if not vendor:
            vendor = self.env["res.partner"].create({"name": "مورد رخام - Simulator", "ref": "SIM-VENDOR-001", "supplier_rank": 1})
        vals = {
            "partner_id": vendor.id,
            "origin": sale.name if sale else "SIM-SALE",
            "order_line": [(0, 0, {"product_id": product.id, "product_qty": 3, "price_unit": 300})],
        }
        rec = self.env["purchase.order"].create(vals)
        return rec, {"state": rec.state, "origin": rec.origin, "amount_total": rec.amount_total}

    def _create_invoice(self, partner, product):
        vals = {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_line_ids": [(0, 0, {"product_id": product.id, "quantity": 1, "price_unit": 451.03})],
        }
        rec = self.env["account.move"].create(vals)
        return rec, {"state": rec.state, "move_type": rec.move_type, "amount_total": rec.amount_total}

    def _create_payment(self, partner, sale):
        journal = self.env["account.journal"].search([("type", "in", ("bank", "cash")), ("company_id", "=", self.env.company.id)], limit=1)
        if not journal:
            raise UserError(_("No Bank/Cash journal exists in the simulator database."))
        vals = {
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": partner.id,
            "amount": 1300,
            "journal_id": journal.id,
            "date": fields.Date.context_today(self),
        }
        if "sale_order_id" in self.env["account.payment"]._fields and sale:
            vals["sale_order_id"] = sale.id
        rec = self.env["account.payment"].create(vals)
        return rec, {"state": rec.state, "amount": rec.amount, "journal": journal.display_name}

    def _create_delivery(self, partner, sale, product):
        picking_type = self.env["stock.picking.type"].search([("code", "=", "outgoing"), ("warehouse_id.company_id", "=", self.env.company.id)], limit=1)
        if not picking_type:
            raise UserError(_("No outgoing picking type exists."))
        vals = {
            "partner_id": partner.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "origin": sale.name if sale else "SIM-SALE",
            "move_ids": [(0, 0, {
                "name": product.display_name,
                "product_id": product.id,
                "product_uom_qty": 1,
                "product_uom": product.uom_id.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
            })],
        }
        rec = self.env["stock.picking"].create(vals)
        return rec, {"state": rec.state, "origin": rec.origin, "picking_type": picking_type.display_name}

    def _create_mrp(self, product, sale):
        vals = {"product_id": product.id, "product_qty": 1, "product_uom_id": product.uom_id.id, "origin": sale.name if sale else "SIM-SALE"}
        rec = self.env["mrp.production"].create(vals)
        return rec, {"state": rec.state, "origin": rec.origin, "product": product.display_name}

    def _create_task(self, partner):
        project = self.env["project.project"].search([("name", "=", "Pre-contract services - Simulator")], limit=1)
        if not project:
            project = self.env["project.project"].create({"name": "Pre-contract services - Simulator", "partner_id": partner.id})
        vals = {"name": "مشروع مول جدة - Simulator", "project_id": project.id, "partner_id": partner.id, "customer_mobile": partner.phone}
        rec = self.env["project.task"].create(vals)
        return rec, {"state": getattr(rec, "state", False), "project": project.display_name, "customer_mobile": rec.customer_mobile}

    def _create_operation_case(self, partner, invoice, task):
        vals = {
            "name": "OPS/SIM/00001",
            "partner_id": partner.id,
            "invoice_id": invoice.id if invoice else False,
            "current_stage": "In Progress",
            "state": "in_progress",
            "service_id": "جدة - وسط جدة",
            "service_family_id": "جدة",
            "routing_name": "توصيل",
            "questionnaire_complete": True,
        }
        rec = self.env["operations.operation.case"].create(vals)
        if task:
            task.operation_case_id = rec.id
        return rec, vals

    def _create_workflow(self, case, invoice):
        vals = {"name": "جديد - %s" % case.name, "operation_case_id": case.id, "invoice_id": invoice.id if invoice else False, "scenario_source": "family_match", "state": "completed", "progress": 100, "idempotency_key": "case:%s:sim" % case.id}
        rec = self.env["operations.workflow.instance"].create(vals)
        return rec, vals

    def _create_question_answer(self, case):
        question = self.env["operations.question"].create({"name": "تحديد معاد التوصيل"})
        option = self.env["operations.question.answer"].create({"name": "قبلها ب 24 ساعه", "question_id": question.id})
        vals = {"operation_case_id": case.id, "question_id": question.id, "answer_id": option.id}
        rec = self.env["operations.question.case.answer"].create(vals)
        return rec, {"question": question.name, "answer": option.name}

    def _create_decor(self, partner, task):
        vals = {"task_id": task.id, "partner_id": partner.id, "customer_name": partner.id, "customer_mobile": partner.phone, "customer_location": "Jeddah simulator location", "visit_datetime": fields.Datetime.now(), "site_readiness": "ready", "state": "otp_sent"}
        rec = self.env["hcos.task.form.decor.measurement"].create(vals)
        return rec, vals

    def _create_installation(self, partner, task):
        vals = {"request_number": "INST/SIM/00001", "task_id": task.id, "partner_id": partner.id, "customer_name": partner.id, "customer_mobile": partner.phone, "customer_location": "https://www.openstreetmap.org/?mlat=21.5540708&mlon=39.1493511", "installation_datetime": fields.Datetime.now(), "installation_status": "completed", "state": "verified", "status": "done", "otp_verified": True}
        rec = self.env["hcos.task.form.installation"].create(vals)
        return rec, vals

    def _create_helpdesk(self, partner, case, task):
        stage = self.env["helpdesk.stage"].search([("name", "=", "In Progress")], limit=1) or self.env["helpdesk.stage"].create({"name": "In Progress"})
        vals = {"name": "Appointment not booked - Simulator", "partner_id": partner.id, "partner_name": partner.name, "partner_phone": partner.phone, "partner_email": partner.email, "stage_id": stage.id, "description": "Customer did not book the appointment sent by WhatsApp.", "task_id": task.id if task else False, "operation_case_id": case.id if case else False}
        rec = self.env["helpdesk.ticket"].create(vals)
        return rec, vals

    def _create_appointment_type(self):
        vals = {"name": "INV/SIM/00001 - Appointment", "appointment_duration": 8, "min_schedule_hours": 24, "max_schedule_days": 60, "auto_confirm": True, "website_url": "/appointment/simulator"}
        rec = self.env["appointment.type"].create(vals)
        return rec, vals

    def _create_calendar_event(self, partner, appointment):
        start = fields.Datetime.now()
        stop = fields.Datetime.add(start, hours=8)
        vals = {"name": "Simulator Appointment Booking", "start": start, "stop": stop, "partner_ids": [(6, 0, [partner.id])], "appointment_type_id": appointment.id, "appointment_status": "booked", "booking_location_url": "https://www.openstreetmap.org/?mlat=21.5540708&mlon=39.1493511"}
        rec = self.env["calendar.event"].create(vals)
        return rec, vals

    def _create_mock_messages(self, records, partner):
        if not self.mock_wati:
            return
        for record in [r for r in records if r]:
            self.env["bayt.alebaa.mock.message"].create({
                "recipient": partner.phone or partner.mobile or partner.x_mobile or "NO_PHONE",
                "template_name": "simulator_%s" % record._name.replace(".", "_"),
                "source_model": record._name,
                "source_record_id": record.id,
                "trigger": "seed/create",
                "payload": json.dumps({"record": record.display_name, "model": record._name}, ensure_ascii=False),
                "status": "would_send" if (partner.phone or partner.mobile or partner.x_mobile) else "blocked",
            })

    def action_run_state_transitions(self):
        self.ensure_one()
        checks = [
            ("CRM stage/state write", "crm.lead", self.env["crm.lead"].search([], order="id desc", limit=1), {"probability": 74.09}),
            ("Sale state write", "sale.order", self.env["sale.order"].search([], order="id desc", limit=1), {}),
            ("Purchase state write", "purchase.order", self.env["purchase.order"].search([], order="id desc", limit=1), {}),
            ("Delivery state-related write", "stock.picking", self.env["stock.picking"].search([], order="id desc", limit=1), {"scheduled_date": fields.Datetime.now()}),
            ("Manufacturing state-related write", "mrp.production", self.env["mrp.production"].search([], order="id desc", limit=1), {"date_start": fields.Datetime.now()}),
            ("Operation Case state change", "operations.operation.case", self.env["operations.operation.case"].search([], order="id desc", limit=1), {"state": "done", "current_stage": "Done"}),
            ("Workflow completion", "operations.workflow.instance", self.env["operations.workflow.instance"].search([], order="id desc", limit=1), {"state": "completed", "progress": 100}),
            ("Helpdesk stage write", "helpdesk.ticket", self.env["helpdesk.ticket"].search([], order="id desc", limit=1), {"priority": "3"}),
            ("Appointment status write", "calendar.event", self.env["calendar.event"].search([("appointment_type_id", "!=", False)], order="id desc", limit=1), {"appointment_status": "booked"}),
        ]
        for scenario, model_name, record, values in checks:
            if not record:
                self._log(scenario, model_name, "fail", message="No simulator record found. Run Seed All first.")
                continue
            try:
                with self.env.cr.savepoint():
                    if values:
                        record.write(values)
                self._log(scenario, model_name, "pass", record=record, payload=values)
            except Exception as exc:
                self._log(scenario, model_name, "fail", record=record, message=str(exc), payload=values)
        self.last_run_at = fields.Datetime.now()
        return self.action_open_results()

    def action_clear_results(self):
        self.env["bayt.alebaa.test.result"].search([]).unlink()
        self.env["bayt.alebaa.mock.message"].search([]).unlink()
        return True

    def action_open_results(self):
        return {"type": "ir.actions.act_window", "name": "Simulator Test Matrix", "res_model": "bayt.alebaa.test.result", "view_mode": "list,form", "target": "current"}

    def action_open_mock_messages(self):
        return {"type": "ir.actions.act_window", "name": "Mock WATI Outbox", "res_model": "bayt.alebaa.mock.message", "view_mode": "list,form", "target": "current"}
