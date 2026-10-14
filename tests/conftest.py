import sys
import os
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospector.store import Store
from prospector.security import hash_password
from prospector import schema as S
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@pytest.fixture(scope="session")
def definitions():
    return {"adrian": {"name": "Adrian", "role": "admin", "password_hash": hash_password("Admin-inicial-teste")},
        "vitor": {"name": "Vitor", "role": "operator", "password_hash": hash_password("123456")}}


@pytest.fixture
def db(tmp_path, definitions):
    postgres_url = os.getenv("TEST_POSTGRES_URL", "")
    if postgres_url:
        parsed = make_url(postgres_url)
        assert parsed.database == "prospector_test" and parsed.host in {"localhost", "127.0.0.1"}, "Use apenas o banco descartável local prospector_test."
        engine = create_engine(postgres_url.replace("postgresql://", "postgresql+psycopg://"))
        S.metadata.drop_all(engine)
        engine.dispose()
    store = Store(postgres_url or "sqlite:///"+str(tmp_path / "test.db"), "cloud" if postgres_url else "local")
    store.bootstrap(definitions)
    yield store
    store.engine.dispose()


@pytest.fixture
def team(db):
    admin = db.change_password(db.login("adrian", "Admin-inicial-teste"), "Adrian-Nova-Senha-2026")
    vitor = db.change_password(db.login("vitor", "123456"), "Vitor-Nova-Senha-2026")
    return admin, vitor
