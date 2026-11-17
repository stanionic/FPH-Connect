"""meol annual programs

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('organization_programs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('organization_programs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_organization_programs_organization_id'),
                              ['organization_id'], unique=False)
        batch_op.create_index('ix_orgprogram_org_year', ['organization_id', 'year'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('organization_programs', schema=None) as batch_op:
        batch_op.drop_index('ix_orgprogram_org_year')
        batch_op.drop_index(batch_op.f('ix_organization_programs_organization_id'))
    op.drop_table('organization_programs')
