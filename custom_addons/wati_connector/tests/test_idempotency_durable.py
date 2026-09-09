import uuid

from odoo.tests.common import TransactionCase

from ..services.idempotency import WatiIdempotency


class _ForceOuterRollback(Exception):
    pass


class TestWatiDurableIdempotency(TransactionCase):

    def setUp(self):
        super().setUp()
        self.idem = WatiIdempotency(self.env)
        token = uuid.uuid4().hex
        self.scope = f"test:durable:{token}"
        self.key = f"request:{token}"

    def tearDown(self):
        self.idem.release_durable(self.scope, self.key)
        super().tearDown()

    def test_durable_key_survives_outer_transaction_rollback(self):
        try:
            with self.env.cr.savepoint():
                self.assertTrue(
                    self.idem.acquire_durable(
                        self.scope,
                        self.key,
                        ttl_seconds=120,
                    )
                )
                raise _ForceOuterRollback()
        except _ForceOuterRollback:
            pass

        # The request transaction rolled back, but the independently committed
        # key must still suppress Odoo's automatic retry of the same action.
        self.assertFalse(
            self.idem.acquire_durable(
                self.scope,
                self.key,
                ttl_seconds=120,
            )
        )

    def test_durable_release_allows_known_safe_retry(self):
        self.assertTrue(self.idem.acquire_durable(self.scope, self.key))
        self.idem.release_durable(self.scope, self.key)
        self.assertTrue(self.idem.acquire_durable(self.scope, self.key))
