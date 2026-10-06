"""create daily_usage table

Revision ID: 3f1a9c2d7b40
Revises: c07e4fd55ec0
Create Date: 2026-10-06 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f1a9c2d7b40'
down_revision: Union[str, Sequence[str], None] = 'c07e4fd55ec0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('daily_usage',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('questions', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('day')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('daily_usage')
