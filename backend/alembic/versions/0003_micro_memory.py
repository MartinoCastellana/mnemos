"""page micro-memory and rank removal"""

from alembic import op
import sqlalchemy as sa

from app.db.models import CadastralPair, EntityCluster, PageMicroMemory, RecoveryRequest

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = [
    PageMicroMemory.__table__,
    EntityCluster.__table__,
    RecoveryRequest.__table__,
    CadastralPair.__table__,
]


def upgrade():
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)
    with op.batch_alter_table("field_results") as batch:
        batch.drop_column("rank")
    with op.batch_alter_table("resolved_fields") as batch:
        batch.drop_column("final_rank")


def downgrade():
    with op.batch_alter_table("resolved_fields") as batch:
        batch.add_column(sa.Column("final_rank", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("field_results") as batch:
        batch.add_column(sa.Column("rank", sa.Integer(), nullable=False, server_default="0"))
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
