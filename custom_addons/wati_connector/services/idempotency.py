import hashlib
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, api, fields


class WatiIdempotency:
    """Database-backed duplicate suppression for outbound user actions.

    Process-local dictionaries are unsafe when Odoo runs multiple workers or
    multiple containers. This service stores short-lived request keys in
    PostgreSQL, so every worker observes the same idempotency state.

    Outbound provider calls need the durable methods below. Odoo may
    automatically retry an HTTP transaction after a serialization failure. If
    the idempotency key is written only in that transaction, the rollback also
    removes the key even though WATI may already have accepted the message.
    A retry would then send the same user action again. Durable acquisition uses
    its own cursor and commit so the guard survives rollback/retry of the outer
    request transaction.
    """

    DEFAULT_TTL_SECONDS = 180

    def __init__(self, env):
        self.env = env
        self.model = env["wati.idempotency.key"].sudo()

    @staticmethod
    def digest(*parts):
        raw = "\x1f".join(str(part or "") for part in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def acquire(self, scope, key, *, ttl_seconds=None):
        scope = str(scope or "").strip()[:120]
        key = str(key or "").strip()[:180]
        if not scope or not key:
            return True

        now = fields.Datetime.now()
        ttl = int(ttl_seconds or self.DEFAULT_TTL_SECONDS)
        expires_at = now + timedelta(seconds=max(1, ttl))

        expired = self.model.search(
            [("scope", "=", scope), ("key", "=", key), ("expires_at", "<=", now)],
            limit=1,
        )
        if expired:
            expired.unlink()

        try:
            with self.env.cr.savepoint():
                self.model.create(
                    {
                        "scope": scope,
                        "key": key,
                        "expires_at": expires_at,
                    }
                )
        except IntegrityError:
            return False
        return True

    def release(self, scope, key):
        scope = str(scope or "").strip()[:120]
        key = str(key or "").strip()[:180]
        if not scope or not key:
            return
        self.model.search(
            [("scope", "=", scope), ("key", "=", key)],
            limit=1,
        ).unlink()

    def acquire_durable(self, scope, key, *, ttl_seconds=None):
        """Acquire a key in an independent committed transaction.

        This method must protect any non-transactional external side effect such
        as sending a WATI message. The committed key remains visible if Odoo
        rolls back and retries the surrounding HTTP request.
        """
        with self.env.registry.cursor() as cr:
            durable_env = api.Environment(cr, SUPERUSER_ID, {})
            acquired = WatiIdempotency(durable_env).acquire(
                scope,
                key,
                ttl_seconds=ttl_seconds,
            )
            cr.commit()
            return acquired

    def release_durable(self, scope, key):
        """Release a durable key after a known pre-acceptance provider failure."""
        with self.env.registry.cursor() as cr:
            durable_env = api.Environment(cr, SUPERUSER_ID, {})
            WatiIdempotency(durable_env).release(scope, key)
            cr.commit()

    def cleanup_expired(self, *, limit=1000):
        now = fields.Datetime.now()
        rows = self.model.search(
            [("expires_at", "<=", now)],
            order="expires_at asc, id asc",
            limit=limit,
        )
        if rows:
            rows.unlink()
        return len(rows)
