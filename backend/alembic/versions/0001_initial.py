"""initial auditable document schema"""

from alembic import op
from app.db import models  # noqa: F401
from app.db.session import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
