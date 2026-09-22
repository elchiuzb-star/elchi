"""communications: encrypted push registration tokens

Owner: A7 (wave 8) - ADR-0022 (push provider = FCM, user decision 17.09.2026).

``device_tokens`` deliberately stored only a SHA-256 of the registration token, because until a provider was
chosen there was nothing to send the token to, and a hash cannot leak. FCM needs the token itself, so the row
now also carries it **encrypted** (AES-256-GCM, ``app.core.secret_box``), never in the clear:

  * ``token_cipher``     - nonce || ciphertext, bound to the device's public id as additional authenticated
                           data, so a ciphertext copied onto another row fails to decrypt instead of silently
                           addressing the wrong device;
  * ``token_key_version``- which derived key sealed it, so a key rotation can re-encrypt row by row instead of
                           logging every device out at once.

``token_hash`` stays and remains the unique lookup key: the hash is what the registration endpoint compares,
and it keeps working for rows registered before this migration (their ciphertext is NULL and they simply
cannot be pushed to until the device registers again).

Rules: additive nullable columns, idempotent, no backfill (we do not have the plaintext); single head.
downgrade() is dev/test only (ADR-0016).

Revision ID: 20260917_0073
Revises: 20260917_0072
Create Date: 2026-09-17 17:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0073"
down_revision: str = "20260917_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.device_tokens ADD COLUMN IF NOT EXISTS token_cipher BYTEA")
    op.execute("ALTER TABLE public.device_tokens ADD COLUMN IF NOT EXISTS token_key_version SMALLINT")
    op.execute("ALTER TABLE public.device_tokens DROP CONSTRAINT IF EXISTS ck_device_tokens_cipher_pair")
    op.execute(
        "ALTER TABLE public.device_tokens ADD CONSTRAINT ck_device_tokens_cipher_pair CHECK ("
        "(token_cipher IS NULL) = (token_key_version IS NULL)) NOT VALID"
    )
    op.execute("ALTER TABLE public.device_tokens VALIDATE CONSTRAINT ck_device_tokens_cipher_pair")
    op.execute(
        "COMMENT ON COLUMN public.device_tokens.token_cipher IS "
        "'ADR-0022: AES-256-GCM sealed push registration token (nonce || ciphertext), AAD = device public id. "
        "NULL for devices registered before 0073 - they re-register before they can be pushed to.'"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): dropping the columns loses the tokens; devices must register again."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.device_tokens DROP CONSTRAINT IF EXISTS ck_device_tokens_cipher_pair")
    op.execute("ALTER TABLE public.device_tokens DROP COLUMN IF EXISTS token_key_version")
    op.execute("ALTER TABLE public.device_tokens DROP COLUMN IF EXISTS token_cipher")
