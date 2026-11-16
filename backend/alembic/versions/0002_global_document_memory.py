"""persistent global document memory tables"""

from alembic import op
from app.db.models import (
    Conflict,
    DocumentCluster,
    EntityCandidate,
    EntityRelationship,
    PageObservation,
    PageSeparation,
    ProcessingRun,
    ResolvedField,
)

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = [
    ProcessingRun.__table__,
    PageObservation.__table__,
    EntityCandidate.__table__,
    EntityRelationship.__table__,
    PageSeparation.__table__,
    DocumentCluster.__table__,
    ResolvedField.__table__,
    Conflict.__table__,
]


def upgrade():
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
