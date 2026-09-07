import hashlib
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields


class WatiIdempotency:
    """Database-backed duplicate suppression for outbound user actions.

    Process-local dictionaries are unsafe when Odoo runs multiple workers or
    multiple containers. This service stores short-lived request keys in
    PostgreSQL, so every worker observes the same idempotency state.
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
