"""numeric_precision_20_9

Revision ID: c8d4e9f2a1b3
Revises: 7f500c3229b9
Create Date: 2026-05-01 12:00:00.000000

Bumps all price/quantity/slippage columns from Numeric(18,8) to Numeric(20,9)
for Alpaca API compatibility (9 decimal places covers BTC sub-satoshi precision
and fractional share quantities without rounding loss).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c8d4e9f2a1b3'
down_revision: Union[str, Sequence[str], None] = '7f500c3229b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_N20_9 = sa.Numeric(20, 9)
_N18_8 = sa.Numeric(18, 8)


def upgrade() -> None:
    with op.batch_alter_table('executions', schema=None) as b:
        b.alter_column('fill_price',  existing_type=_N18_8, type_=_N20_9, existing_nullable=False)
        b.alter_column('qty',         existing_type=_N18_8, type_=_N20_9, existing_nullable=False)
        b.alter_column('slippage',    existing_type=_N18_8, type_=_N20_9, existing_nullable=False)
        b.alter_column('bid_price',   existing_type=_N18_8, type_=_N20_9, existing_nullable=True)
        b.alter_column('ask_price',   existing_type=_N18_8, type_=_N20_9, existing_nullable=True)
        b.alter_column('strike_price',existing_type=_N18_8, type_=_N20_9, existing_nullable=True)

    with op.batch_alter_table('closed_trades', schema=None) as b:
        b.alter_column('qty',             existing_type=_N18_8, type_=_N20_9, existing_nullable=False)
        b.alter_column('avg_entry_price', existing_type=_N18_8, type_=_N20_9, existing_nullable=False)
        b.alter_column('avg_exit_price',  existing_type=_N18_8, type_=_N20_9, existing_nullable=False)
        b.alter_column('strike_price',    existing_type=_N18_8, type_=_N20_9, existing_nullable=True)

    with op.batch_alter_table('market_condition_snapshots', schema=None) as b:
        b.alter_column('bid_price', existing_type=_N18_8, type_=_N20_9, existing_nullable=False)
        b.alter_column('ask_price', existing_type=_N18_8, type_=_N20_9, existing_nullable=False)

    with op.batch_alter_table('reflection_logs', schema=None) as b:
        b.alter_column('entry_price', existing_type=_N18_8, type_=_N20_9, existing_nullable=True)
        b.alter_column('exit_price',  existing_type=_N18_8, type_=_N20_9, existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('reflection_logs', schema=None) as b:
        b.alter_column('entry_price', existing_type=_N20_9, type_=_N18_8, existing_nullable=True)
        b.alter_column('exit_price',  existing_type=_N20_9, type_=_N18_8, existing_nullable=True)

    with op.batch_alter_table('market_condition_snapshots', schema=None) as b:
        b.alter_column('bid_price', existing_type=_N20_9, type_=_N18_8, existing_nullable=False)
        b.alter_column('ask_price', existing_type=_N20_9, type_=_N18_8, existing_nullable=False)

    with op.batch_alter_table('closed_trades', schema=None) as b:
        b.alter_column('qty',             existing_type=_N20_9, type_=_N18_8, existing_nullable=False)
        b.alter_column('avg_entry_price', existing_type=_N20_9, type_=_N18_8, existing_nullable=False)
        b.alter_column('avg_exit_price',  existing_type=_N20_9, type_=_N18_8, existing_nullable=False)
        b.alter_column('strike_price',    existing_type=_N20_9, type_=_N18_8, existing_nullable=True)

    with op.batch_alter_table('executions', schema=None) as b:
        b.alter_column('fill_price',  existing_type=_N20_9, type_=_N18_8, existing_nullable=False)
        b.alter_column('qty',         existing_type=_N20_9, type_=_N18_8, existing_nullable=False)
        b.alter_column('slippage',    existing_type=_N20_9, type_=_N18_8, existing_nullable=False)
        b.alter_column('bid_price',   existing_type=_N20_9, type_=_N18_8, existing_nullable=True)
        b.alter_column('ask_price',   existing_type=_N20_9, type_=_N18_8, existing_nullable=True)
        b.alter_column('strike_price',existing_type=_N20_9, type_=_N18_8, existing_nullable=True)
