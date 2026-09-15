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


def _group_id(cr, external_name):
    cr.execute(
        """
        SELECT res_id
          FROM ir_model_data
         WHERE module = 'wati_connector'
           AND name = %s
           AND model = 'res.groups'
         LIMIT 1
        """,
        (external_name,),
    )
    row = cr.fetchone()
    return row[0] if row else None


def _add_users_to_group(cr, group_id, where_sql):
    if not group_id or not _table_exists(cr, "res_groups_users_rel"):
        return
    cr.execute(
        f"""
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT %s, u.id
          FROM res_users u
         WHERE {where_sql}
           AND NOT EXISTS (
               SELECT 1
                 FROM res_groups_users_rel rel
                WHERE rel.gid = %s
                  AND rel.uid = u.id
           )
        """,
        (group_id, group_id),
    )


def _migrate_legacy_wati_roles(cr):
    """Preserve existing WATI operators while moving to role-based security."""
    if not _table_exists(cr, "res_users"):
        return

    agent_group_id = _group_id(cr, "group_wati_agent")
    if _column_exists(cr, "res_users", "wati_operator_email"):
        _add_users_to_group(
            cr,
            agent_group_id,
            "COALESCE(NULLIF(BTRIM(u.wati_operator_email), ''), '') <> ''",
        )

    supervisor_group_id = _group_id(cr, "group_wati_supervisor")
    if _column_exists(cr, "res_users", "wati_is_supervisor"):
        _add_users_to_group(cr, supervisor_group_id, "u.wati_is_supervisor IS TRUE")


def migrate(cr, version):
    """Normalize historical data when upgrading to 19.0.9.0.0.

    Migrations are versioned and idempotent. Product data files must never run
    one-off repair functions during every module update.
    """
    _migrate_legacy_wati_roles(cr)

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
