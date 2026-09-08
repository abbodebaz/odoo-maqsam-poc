import json

from odoo.tests.common import TransactionCase

from ..models.wati_automation_template_contract import _build_template_contract


class TestWatiTemplateContract(TransactionCase):
    def setUp(self):
        super().setUp()
        model = self.env["ir.model"]._get("res.partner")
        self.rule = self.env["wati.automation.rule"].create(
            {
                "name": "Template contract test",
                "model_id": model.id,
                "active": False,
            }
        )

    def test_positional_body_uses_exact_wati_api_name(self):
        contract = _build_template_contract(
            {
                "elementName": "aa2a",
                "body": "مرحبا {{1}}، كيف نقدر نخدمك؟",
                "customParams": [{"name": "name"}],
            }
        )
        self.assertEqual(contract["state"], "valid")
        self.assertEqual(
            [(slot["token"], slot["api_name"]) for slot in contract["slots"]],
            [("1", "name")],
        )

    def test_mismatched_live_contract_fails_closed(self):
        contract = _build_template_contract(
            {
                "elementName": "unsafe",
                "body": "Hello {{1}}",
                "customParams": [{"name": "name"}, {"name": "order_number"}],
            }
        )
        self.assertEqual(contract["state"], "invalid")
        self.assertIn("تم منع التفعيل", contract["message"])

    def test_contract_keeps_visible_token_separate_from_api_name(self):
        contract = _build_template_contract(
            {
                "elementName": "aa2a",
                "body": "Hello {{1}}",
                "customParams": [{"name": "name"}],
            }
        )
        self.rule._store_contract(contract)
        self.rule._apply_template_contract(contract, reason="test")

        line = self.rule.parameter_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.param_name, "1")
        self.assertEqual(line.placeholder_token, "1")
        self.assertEqual(line.api_param_name, "name")
        self.assertEqual(line.template_variable_label, "{{1}}")

    def test_send_payload_uses_api_name_not_visible_placeholder(self):
        contract = _build_template_contract(
            {
                "elementName": "aa2a",
                "body": "Hello {{1}}",
                "customParams": [{"name": "name"}],
            }
        )
        self.rule._store_contract(contract)
        self.rule._apply_template_contract(contract, reason="test_send")
        self.rule.parameter_ids.write({"source_type": "record_name"})
        partner = self.env["res.partner"].create({"name": "Abdulrhman"})

        params, error = self.rule._contract_send_params(partner)
        self.assertFalse(error)
        self.assertEqual(params, [{"name": "name", "value": "Abdulrhman"}])

    def test_legacy_rebuild_does_not_destroy_api_alias(self):
        contract = _build_template_contract(
            {
                "elementName": "aa2a",
                "body": "Hello {{1}}",
                "customParams": [{"name": "name"}],
            }
        )
        self.rule.with_context(wati_contract_internal=True).write(
            {
                "template_name": "aa2a",
                "template_body": "Hello {{1}}",
                "template_contract_json": json.dumps(contract),
                "template_contract_state": "valid",
                "template_contract_message": "ok",
            }
        )
        self.rule._apply_template_contract(contract, reason="initial")
        self.rule._hard_rebuild_template_parameters(reason="legacy_guard")

        line = self.rule.parameter_ids
        self.assertEqual(line.param_name, "1")
        self.assertEqual(line.api_param_name, "name")
