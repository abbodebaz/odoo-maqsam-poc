# 19.0.11.0.1 migration

This release replaces the removed Odoo 18-era `_sql_constraints` declaration with the Odoo 19 `models.Constraint` API for WATI idempotency keys.

The post-migration hook verifies that PostgreSQL actually contains the `(scope, key)` unique constraint after the ORM upgrade.
