import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app, auth_limiter, money_limiter

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]
test_engine = create_engine(TEST_DATABASE_URL)
TestSession = sessionmaker(bind=test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

# Rate limits are switched off in tests, except the one test that checks them.
auth_limiter.enabled = False
money_limiter.enabled = False


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.create_all(bind=test_engine)
    with test_engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE users, accounts, idempotency_keys, ledger_entries "
            "RESTART IDENTITY CASCADE"
        ))
    yield