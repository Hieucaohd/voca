"""Imports every model so SQLAlchemy metadata (and Alembic autogenerate) sees all tables."""
from app.modules.auth.models import RefreshToken, User  # noqa: F401
from app.modules.collections.models import Collection, CollectionMember, CollectionWord  # noqa: F401
from app.modules.external.models import ApiKey, ExternalApplication  # noqa: F401
from app.modules.learning.models import CardProgress, DailyActivity, ReviewLog, StudyPlan  # noqa: F401
from app.modules.vocabulary.models import (  # noqa: F401
    Language,
    MediaAsset,
    Source,
    Tag,
    Vocabulary,
    VocabularyContext,
    VocabularyExample,
    VocabularySense,
)
