import json

from odoo.tests.common import TransactionCase


class TestWatiTemplateSwitch(TransactionCase):
    def setUp(self):
        super().setUp()
        model = self.env["ir.model"]._get("res.partner")
        self.rule = self.env["wati.automation.rule"].create({
            "name": "Template switch test",
            "model_id": model.id,
            "active": False,
        })

    def _choice(self, name, body, params):
        return self.env["wati.automation.template.choice"].create({
            "rule_id": self.rule.id,
            "name": name,
            "body": body,
            "param_names_json": json.dumps(params),
        })

    def test_selecting_new_template_hard_replaces_old_rows(self):
        self.env["wati.automation.parameter"].create([
            {"rule_id": self.rule.id, "param_name": "old_a"},
            {"rule_id": self.rule.id, "param_name": "old_b"},
        ])

        self._choice("one_var", "Hello {{1}}", ["stale_name"]).action_select()
        self.assertEqual(self.rule.parameter_ids.mapped("param_name"), ["1"])

        self._choice(
            "two_vars",
            "Hello {{1}} {{2}}",
            ["first", "second", "stale_extra"],
        ).action_select()
        self.assertEqual(
            self.rule.parameter_ids.sorted("sequence").mapped("param_name"),
            ["1", "2"],
        )
        self.assertEqual(self.rule.template_name, "two_vars")

    def test_resync_removes_legacy_accumulated_rows_from_current_body(self):
        self._choice("one_var", "Hello {{1}}", ["1"]).action_select()
        self.env["wati.automation.parameter"].create([
            {"rule_id": self.rule.id, "param_name": "services"},
            {"rule_id": self.rule.id, "param_name": "serdate"},
            {"rule_id": self.rule.id, "param_name": "sertime"},
            {"rule_id": self.rule.id, "param_name": "2"},
            {"rule_id": self.rule.id, "param_name": "3"},
            {"rule_id": self.rule.id, "param_name": "name"},
            {"rule_id": self.rule.id, "param_name": "cr2name"},
            {"rule_id": self.rule.id, "param_name": "cr2id"},
        ])
        self.assertEqual(len(self.rule.parameter_ids), 9)

        self.rule.action_fetch_template_params()
        self.assertEqual(self.rule.parameter_ids.mapped("param_name"), ["1"])

    def test_direct_template_write_never_keeps_previous_rows(self):
        self._choice("first", "Hi {{1}} {{2}}", ["first", "second"]).action_select()
        self.assertEqual(self.rule.parameter_ids.mapped("param_name"), ["1", "2"])

        self.rule.write({
            "template_name": "second",
            "template_body": "Only {{1}}",
            "template_param_names_json": json.dumps(["wrong", "metadata"]),
        })
        self.assertEqual(self.rule.parameter_ids.mapped("param_name"), ["1"])

    def test_final_upgrade_repair_cleans_saved_legacy_rows(self):
        self._choice("one_var", "Hello {{1}}", ["1"]).action_select()
        self.env["wati.automation.parameter"].create([
            {"rule_id": self.rule.id, "param_name": "services"},
            {"rule_id": self.rule.id, "param_name": "serdate"},
            {"rule_id": self.rule.id, "param_name": "sertime"},
        ])
        self.assertEqual(len(self.rule.parameter_ids), 4)

        self.env["wati.automation.rule"]._repair_template_integrity_final()
        self.rule.invalidate_recordset(["parameter_ids"])
        self.assertEqual(self.rule.parameter_ids.mapped("param_name"), ["1"])
