from odoo.tests.common import TransactionCase


class TestWatiTemplateVariableSave(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()

    def test_create_repairs_readonly_variable_values_omitted_by_web_client(self):
        template = self.Template.create(
            {
                "name": "order_ready_save_test",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا {{name}}، طلبك أصبح جاهزًا.",
                # This reproduces the Odoo form payload seen when readonly
                # name/position values are displayed but omitted on parent save.
                "variable_ids": [(0, 0, {"sample_value": "أحمد"})],
            }
        )

        self.assertEqual(len(template.variable_ids), 1)
        self.assertEqual(template.variable_ids.name, "name")
        self.assertEqual(template.variable_ids.position, 1)
        self.assertEqual(template.variable_ids.sample_value, "أحمد")

    def test_create_repairs_multiple_variables_by_body_order(self):
        template = self.Template.create(
            {
                "name": "order_ready_multi_save_test",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا {{name}}، رقم الطلب {{order_id}} جاهز.",
                "variable_ids": [
                    (0, 0, {"sample_value": "أحمد"}),
                    (0, 0, {"sample_value": "SO-1001"}),
                ],
            }
        )

        rows = template.variable_ids.sorted("position")
        self.assertEqual(rows.mapped("name"), ["name", "order_id"])
        self.assertEqual(rows.mapped("position"), [1, 2])
        self.assertEqual(rows.mapped("sample_value"), ["أحمد", "SO-1001"])
