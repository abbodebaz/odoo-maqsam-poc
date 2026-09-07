from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.wati_connector.services.config import WatiConfig
from odoo.addons.wati_connector.services.exceptions import WatiConfigurationError


@tagged("post_install", "-at_install")
class TestWatiConfig(TransactionCase):

    def test_endpoint_normalization_removes_api_suffix(self):
        self.assertEqual(
            WatiConfig.normalize_endpoint("https://tenant.example.com/api/v1/sendSessionMessage"),
            "https://tenant.example.com",
        )

    def test_endpoint_normalization_keeps_tenant_path(self):
        self.assertEqual(
            WatiConfig.normalize_endpoint("https://example.com/tenant-a/"),
            "https://example.com/tenant-a",
        )

    def test_endpoint_requires_http_scheme(self):
        with self.assertRaises(WatiConfigurationError):
            WatiConfig.normalize_endpoint("tenant.example.com")

    def test_token_normalization_accepts_bearer_prefix(self):
        self.assertEqual(WatiConfig.normalize_token("Bearer abc123"), "abc123")
        self.assertEqual(WatiConfig.normalize_token("abc123"), "abc123")
