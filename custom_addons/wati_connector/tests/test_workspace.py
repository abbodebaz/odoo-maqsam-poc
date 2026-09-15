from odoo.tests.common import TransactionCase


class TestWatiWorkspace(TransactionCase):

    def setUp(self):
        super().setUp()
        self.gateway = self.env["wati.workspace.gateway"]

    def test_dashboard_contract_contains_core_services_and_kpis(self):
        data = self.gateway.get_dashboard_data()

        self.assertIn("features", data)
        self.assertIn("kpis", data)
        self.assertIn("onboarding", data)
        feature_ids = {feature["id"] for feature in data["features"]}
        self.assertTrue({"inbox", "messages", "automation", "help"}.issubset(feature_ids))
        self.assertEqual(data["onboarding_total"], 4)
        self.assertTrue(
            {
                "unread_conversations",
                "messages_24h",
                "active_automations",
                "webhook_attention",
            }.issubset(data["kpis"])
        )

    def test_help_center_has_searchable_structured_articles(self):
        data = self.gateway.get_help_content()
        self.assertTrue(data["sections"])
        article_ids = {
            article["id"]
            for section in data["sections"]
            for article in section.get("articles", [])
        }
        self.assertIn("connect-wati", article_ids)
        self.assertIn("first-automation", article_ids)
        self.assertIn("webhook-monitor", article_ids)
