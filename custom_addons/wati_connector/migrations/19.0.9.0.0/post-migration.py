def _table_exists(cr, table_name):
    cr.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    return bool(cr.fetchone()[0])


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = %s
           AND column_name = %s
         LIMIT 1
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone())


def _migrate_legacy_supervisors(cr):
    """Move the legacy boolean permission to the WATI Supervisor group."""
    if not _table_exists(cr, "res_users") or not _column_exists(
        cr, "res_users", "wati_is_supervisor"
    ):
        return
    if not _table_exists(cr, "res_groups_users_rel"):
        return

    cr.execute(
        """
        SELECT res_id
          FROM ir_model_data
         WHERE module = 'wati_connector'
           AND name = 'group_wati_supervisor'
           AND model = 'res.groups'
         LIMIT 1
        """
    )
    row = cr.fetchone()
    if not row:
        return
    group_id = row[0]

    cr.execute(
        """
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT %s, u.id
          FROM res_users u
         WHERE u.wati_is_supervisor IS TRUE
           AND NOT EXISTS (
               SELECT 1
                 FROM res_groups_users_rel rel
                WHERE rel.gid = %s
                  AND rel.uid = u.id
           )
        """,
        (group_id, group_id),
    )


def migrate(cr, version):
    """Normalize historical data when upgrading to 19.0.9.0.0.

    Migrations are versioned and idempotent. Product data files must never run
    one-off repair functions during every module update.
    """
    _migrate_legacy_supervisors(cr)

    rule_table = "wati_automation_rule"
    if _table_exists(cr, rule_table) and _column_exists(cr, rule_table, "setup_step"):
        cr.execute(
            "UPDATE wati_automation_rule SET setup_step = 'review' WHERE active IS TRUE"
        )

    log_table = "wati_automation_log"
    required = ("status", "response_excerpt", "error_message")
    if _table_exists(cr, log_table) and all(
        _column_exists(cr, log_table, column) for column in required
    ):
        cr.execute(
            """
            UPDATE wati_automation_log
               SET status = 'failed',
                   error_message = COALESCE(
                       NULLIF(error_message, ''),
                       'WATI returned result=false; historical status corrected during migration.'
                   )
             WHERE status = 'sent'
               AND response_excerpt ILIKE '%"result":false%'
            """
        )
