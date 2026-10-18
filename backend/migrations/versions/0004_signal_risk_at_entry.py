"""open risk when a signal was published

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('signals') as batch:
        batch.add_column(sa.Column('risk_at_entry', sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('signals') as batch:
        batch.drop_column('risk_at_entry')
