"""Add users.temp_password_expires_at

Revision ID: b8d4f0e2a6c1
Revises: a7c3e9d1f2b4
Create Date: 2026-10-01 10:00:00.000000

Emailed temporary passwords (new employee / "resend login details") now expire
after TEMP_PASSWORD_EXPIRE_DAYS. NULL means no temporary password is
outstanding, so existing accounts are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8d4f0e2a6c1'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9d1f2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('temp_password_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'temp_password_expires_at')
