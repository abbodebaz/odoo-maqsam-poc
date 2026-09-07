from odoo import fields, models


class WatiIdempotencyKey(models.Model):
    _name = "wati.idempotency.key"
    _description = "WATI Idempotency Key"
    _order = "expires_at desc, id desc"

    scope = fields.Char(required=True, index=True)
    key = fields.Char(required=True, index=True)
    expires_at = fields.Datetime(required=True, index=True)

    _sql_constraints = [
        (
            "wati_idempotency_scope_key_unique",
            "unique(scope, key)",
            "The WATI request has already been processed.",
        )
    ]
