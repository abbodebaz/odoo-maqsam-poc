from odoo.tests.common import TransactionCase


class TestWatiSmartButton(TransactionCase):
    def test_model_is_registered(self):
        self.assertIn("wati.smart.button.location", self.env)
