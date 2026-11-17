"""partage de fichiers reseau et permissions nominales

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('extra_permissions', sa.JSON(), nullable=False,
                                      server_default='[]'))
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('visibility', sa.String(length=20), nullable=False,
                                      server_default='scope'))
        batch_op.add_column(sa.Column('share_note', sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('share_note')
        batch_op.drop_column('visibility')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('extra_permissions')
