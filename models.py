from sqlalchemy import Column, Integer, String, Numeric, JSON, DateTime, ForeignKey, func
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


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    kind = Column(String, nullable=False)
    transfer_ref = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())