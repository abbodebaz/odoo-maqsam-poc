from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.wati_connector.utils.phone import (
    equivalent_variants,
    normalize_whatsapp_number,
    phone_identity,
)


@tagged("post_install", "-at_install")
class TestWatiPhoneUtils(TransactionCase):

    def test_saudi_formats_normalize_to_same_number(self):
        expected = "966501234567"
        for value in (
            "+966501234567",
            "00966501234567",
            "0501234567",
            "501234567",
        ):
            self.assertEqual(normalize_whatsapp_number(value), expected)

    def test_unknown_international_number_is_not_rewritten(self):
        self.assertEqual(normalize_whatsapp_number("+14155552671"), "14155552671")

    def test_phone_identity_produces_e164_local_and_suffix(self):
        identity = phone_identity("0501234567")
        self.assertEqual(identity["e164"], "+966501234567")
        self.assertEqual(identity["local"], "0501234567")
        self.assertEqual(identity["suffix"], "501234567")

    def test_equivalent_variants_are_unique(self):
        variants = equivalent_variants("+966501234567")
        self.assertEqual(
            variants,
            ["966501234567", "+966501234567", "0501234567"],
        )
