from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, func,
)
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("balance >= 0", name="balance_non_negative"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    balance = Column(Numeric(12, 2), nullable=False, default=0)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key = Column(String, primary_key=True)
    request_hash = Column(String, nullable=False)
    response = Column(JSON, nullable=True)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    kind = Column(String, nullable=False)
    transfer_ref = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())