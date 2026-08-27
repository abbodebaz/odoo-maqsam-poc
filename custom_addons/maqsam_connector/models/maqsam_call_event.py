from odoo import fields, models


class MaqsamCallEvent(models.Model):
    _name = "maqsam.call.event"
    _description = "Maqsam Call Event"
    _order = "received_at desc, id desc"

    call_id = fields.Char(index=True)
    caller = fields.Char()
    callee = fields.Char()
    caller_number = fields.Char(index=True)
    callee_number = fields.Char(index=True)
    state = fields.Char(index=True)
    direction = fields.Char(index=True)
    event_timestamp = fields.Integer()
    duration = fields.Integer()
    handling_time = fields.Integer()
    agents_json = fields.Text()
    payload_json = fields.Text(required=True)
    received_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
