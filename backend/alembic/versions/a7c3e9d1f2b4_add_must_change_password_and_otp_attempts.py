"""Add users.must_change_password and otp_records.attempts

Revision ID: a7c3e9d1f2b4
Revises: 77e63f4240ef
Create Date: 2026-09-30 10:00:00.000000

must_change_password forces a newly created employee to replace the emailed
temporary password on first login. Existing accounts default to false so
nobody already using the system is interrupted.

otp_records.attempts counts wrong guesses against a password-reset OTP so the
code is burned after a few failures, independent of the per-IP rate limit.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7c3e9d1f2b4'
down_revision: Union[str, Sequence[str], None] = '77e63f4240ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('otp_records', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('otp_records', 'attempts')
    op.drop_column('users', 'must_change_password')
