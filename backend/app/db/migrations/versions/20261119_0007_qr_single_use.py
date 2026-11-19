"""QR single-use passes (visits and suppliers)

- qr_credentials.single_use: the first GRANTED scan consumes the pass (it is revoked right away).
  Existing credentials keep working as before (single_use = false).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19 09:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('qr_credentials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('single_use', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('qr_credentials', schema=None) as batch_op:
        batch_op.drop_column('single_use')
