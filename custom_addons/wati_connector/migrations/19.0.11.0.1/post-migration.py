def migrate(cr, version):
    """Verify the Odoo 19 idempotency constraint after the ORM upgrade."""
    cr.execute(
        """
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'wati_idempotency_key'::regclass
           AND contype = 'u'
           AND lower(pg_get_constraintdef(oid)) = 'unique (scope, key)'
         LIMIT 1
        """
    )
    if not cr.fetchone():
        raise RuntimeError(
            "WATI idempotency unique constraint was not created during upgrade"
        )
