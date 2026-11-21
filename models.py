from sqlalchemy import Column, Integer, String, Numeric, JSON
from database import Base


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    owner = Column(String, nullable=False)
    balance = Column(Numeric(12, 2), nullable=False, default=0)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key = Column(String, primary_key=True)
    response = Column(JSON, nullable=True)