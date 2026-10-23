"""morning carry-over of night setups

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23 09:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('signals') as batch:
        batch.add_column(sa.Column('carried_from', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                                   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('signals') as batch:
        batch.drop_column('carried_from')
