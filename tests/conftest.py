"""Fixtures compartilhadas para a suite de testes."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def in_memory_db(monkeypatch):
    """Substitui ``SessionLocal`` por um engine SQLite em memória.

    Garante que cada teste rode contra um banco isolado, sem efeitos
    colaterais no arquivo ``data/aviator.db``.
    """
    from app import database as db_module
    from app.database import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    TestSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    # Garante que os modelos estão registrados no Base.metadata.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    # Os módulos do coletor importam SessionLocal pelo nome diretamente,
    # então também precisamos sobrescrever lá.
    from app.collector import browser as browser_mod
    from app.collector import manual as manual_mod
    from app.collector import manager as manager_mod

    monkeypatch.setattr(browser_mod, "SessionLocal", TestSession)
    monkeypatch.setattr(manual_mod, "SessionLocal", TestSession)
    monkeypatch.setattr(manager_mod, "SessionLocal", TestSession)

    yield TestSession
