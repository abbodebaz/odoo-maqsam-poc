from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ..services.client import WatiClient


class _EmptyTemplateResponse:
    def json(self):
        return {"messageTemplates": []}


class TestWatiTemplateButtonCompat(TransactionCase):

    def test_list_header_sync_accepts_odoo19_extra_rpc_argument(self):
        templates = self.env["wati.template"]
        with patch.object(
            WatiClient,
            "get_message_templates",
            return_value=_EmptyTemplateResponse(),
        ):
            action = templates.action_sync_from_wati([])

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "display_notification")
