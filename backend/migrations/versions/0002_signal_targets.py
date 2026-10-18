"""multiple take-profit targets (TP1 / TP2 / TP3) and break-even stop

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 12:00:00
"""

from alembic import op
import sqlalchemy as sa
import app.db


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('signals') as batch:
        batch.add_column(sa.Column('targets', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('breakeven', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column('stop_current', sa.Double(), nullable=True))
        batch.add_column(sa.Column('fills', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('targets_hit', sa.SmallInteger(), server_default=sa.text('0'), nullable=False))
        batch.add_column(sa.Column('tp1_at', app.db.UTCDateTime(timezone=True), nullable=True))
    # single-target signals recorded before this revision: a take-profit exit counts as TP1 reached
    op.execute("UPDATE signals SET targets_hit = 1, tp1_at = exit_at WHERE exit_reason = 'TP'")


def downgrade() -> None:
    with op.batch_alter_table('signals') as batch:
        for col in ('tp1_at', 'targets_hit', 'fills', 'stop_current', 'breakeven', 'targets'):
            batch.drop_column(col)
