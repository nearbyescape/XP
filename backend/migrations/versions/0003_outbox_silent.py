"""silent Telegram delivery (updates outside the publishing session)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18 18:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('telegram_outbox') as batch:
        batch.add_column(sa.Column('silent', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('telegram_outbox') as batch:
        batch.drop_column('silent')
