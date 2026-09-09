from odoo.tests.common import TransactionCase

from ..services.feature_access import get_feature_mode, sync_feature_access_controls


class TestWatiFeatureAccess(TransactionCase):

    def setUp(self):
        super().setUp()
        self.config = self.env["ir.config_parameter"].sudo()
        self.user_group = self.env.ref("wati_connector.group_wati_user")
        self.admin_group = self.env.ref("wati_connector.group_wati_admin")
        self.system_group = self.env.ref("base.group_system")

    def test_automation_admin_policy_updates_menu_and_acl(self):
        self.config.set_param("wati_connector.access_automation", "admin")
        sync_feature_access_controls(self.env, ["automation"])

        menu = self.env.ref("wati_connector.menu_wati_automation_rules")
        access = self.env.ref("wati_connector.access_wati_automation_rule_admin")

        self.assertEqual(get_feature_mode(self.env, "automation"), "admin")
        self.assertIn(self.admin_group, menu.group_ids)
        self.assertIn(self.system_group, menu.group_ids)
        self.assertNotIn(self.user_group, menu.group_ids)
        self.assertEqual(access.group_id, self.admin_group)

    def test_automation_all_policy_updates_menu_and_acl(self):
        self.config.set_param("wati_connector.access_automation", "all")
        sync_feature_access_controls(self.env, ["automation"])

        menu = self.env.ref("wati_connector.menu_wati_automation_rules")
        access = self.env.ref("wati_connector.access_wati_automation_rule_admin")

        self.assertEqual(get_feature_mode(self.env, "automation"), "all")
        self.assertIn(self.user_group, menu.group_ids)
        self.assertIn(self.system_group, menu.group_ids)
        self.assertEqual(access.group_id, self.user_group)

    def test_template_policy_updates_menu_and_both_model_acls(self):
        self.config.set_param("wati_connector.access_templates", "admin")
        sync_feature_access_controls(self.env, ["templates"])

        menu = self.env.ref("wati_connector.menu_wati_templates")
        template_access = self.env.ref("wati_connector.access_wati_template_admin")
        variable_access = self.env.ref(
            "wati_connector.access_wati_template_variable_admin"
        )

        self.assertEqual(get_feature_mode(self.env, "templates"), "admin")
        self.assertIn(self.admin_group, menu.group_ids)
        self.assertNotIn(self.user_group, menu.group_ids)
        self.assertEqual(template_access.group_id, self.admin_group)
        self.assertEqual(variable_access.group_id, self.admin_group)

        self.config.set_param("wati_connector.access_templates", "all")
        sync_feature_access_controls(self.env, ["templates"])
        self.assertIn(self.user_group, menu.group_ids)
        self.assertEqual(template_access.group_id, self.user_group)
        self.assertEqual(variable_access.group_id, self.user_group)

    def test_history_policy_changes_menu_without_revoking_inbox_models(self):
        self.config.set_param("wati_connector.access_conversations", "admin")
        sync_feature_access_controls(self.env, ["conversations"])

        menu = self.env.ref("wati_connector.menu_wati_conversations")
        base_access = self.env.ref("wati_connector.access_wati_conversation_user")

        self.assertIn(self.admin_group, menu.group_ids)
        self.assertNotIn(self.user_group, menu.group_ids)
        # Inbox agents still need the underlying conversation model. Only the
        # historical feature screen is restricted.
        self.assertEqual(base_access.group_id, self.user_group)
