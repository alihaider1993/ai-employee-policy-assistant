"""add cache_version and sources to conversations

Revision ID: 8b2e5d1f4c63
Revises: 3f1a9c2d7b40
Create Date: 2026-10-06 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b2e5d1f4c63'
down_revision: Union[str, Sequence[str], None] = '3f1a9c2d7b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows get '0', so the app (CACHE_VERSION '1') ignores them.
    op.add_column('conversations', sa.Column('cache_version', sa.String(length=32), server_default='0', nullable=False))
    op.add_column('conversations', sa.Column('sources', sa.JSON(), nullable=True))
    op.create_index('ix_conversations_cache_version_question', 'conversations', ['cache_version', 'question'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_conversations_cache_version_question', table_name='conversations')
    op.drop_column('conversations', 'sources')
    op.drop_column('conversations', 'cache_version')
