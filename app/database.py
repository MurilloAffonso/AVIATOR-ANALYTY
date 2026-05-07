from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    from app.models import RoundResult  # noqa: F401
    from app.player_analytics.models import RoundSnapshotORM  # noqa: F401

    Base.metadata.create_all(bind=engine)
