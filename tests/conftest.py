# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app  # registra todos los modelos en Base.metadata

API_KEY = "test-api-key"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},  # el endpoint corre en otro hilo
        poolclass=StaticPool,  # una sola conexión: la base en memoria es compartida
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


@pytest.fixture
def client(session_factory, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # sin `with`: el lifespan no corre y no toca la base real
    yield TestClient(app, headers={"X-API-Key": API_KEY})
    app.dependency_overrides.clear()
