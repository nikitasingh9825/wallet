from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import engine, Base, get_db
import models

Base.metadata.create_all(bind=engine)
app = FastAPI()


class AccountCreate(BaseModel):
    owner: str


class Amount(BaseModel):
    amount: Decimal = Field(gt=0)


class Transfer(BaseModel):
    from_id: int
    to_id: int
    amount: Decimal = Field(gt=0)


def get_account_or_404(db: Session, account_id: int, lock: bool = False):
    account = db.get(models.Account, account_id, with_for_update=lock)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.post("/accounts")
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    account = models.Account(owner=data.owner, balance=0)
    db.add(account)
    db.commit()
    db.refresh(account)
    return {"id": account.id, "owner": account.owner, "balance": account.balance}


@app.get("/accounts/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_id)
    return {"id": account.id, "owner": account.owner, "balance": account.balance}


@app.get("/accounts/{account_id}/ledger")
def get_ledger(account_id: int, db: Session = Depends(get_db)):
    get_account_or_404(db, account_id)
    entries = (
        db.query(models.LedgerEntry)
        .filter_by(account_id=account_id)
        .order_by(models.LedgerEntry.id)
        .all()
    )
    return [
        {
            "id": e.id,
            "amount": str(e.amount),
            "kind": e.kind,
            "transfer_ref": e.transfer_ref,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@app.post("/accounts/{account_id}/deposit")
def deposit(account_id: int, data: Amount, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_id, lock=True)
    account.balance = account.balance + data.amount
    db.add(models.LedgerEntry(account_id=account.id, amount=data.amount, kind="deposit"))
    db.commit()
    return {"id": account.id, "balance": account.balance}


@app.post("/accounts/{account_id}/withdraw")
def withdraw(account_id: int, data: Amount, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_id, lock=True)
    if account.balance < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")
    account.balance = account.balance - data.amount
    db.add(models.LedgerEntry(account_id=account.id, amount=-data.amount, kind="withdraw"))
    db.commit()
    return {"id": account.id, "balance": account.balance}


@app.post("/transfer")
def transfer(
    data: Transfer,
    idempotency_key: str = Header(...),
    db: Session = Depends(get_db),
):
    if data.from_id == data.to_id:
        raise HTTPException(status_code=400, detail="Cannot transfer to the same account")

    record = models.IdempotencyKey(key=idempotency_key, response=None)
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        saved = db.get(models.IdempotencyKey, idempotency_key)
        return saved.response

    first_id, second_id = sorted([data.from_id, data.to_id])
    first = get_account_or_404(db, first_id, lock=True)
    second = get_account_or_404(db, second_id, lock=True)

    sender = first if first.id == data.from_id else second
    receiver = second if sender is first else first

    if sender.balance < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")
    sender.balance = sender.balance - data.amount
    receiver.balance = receiver.balance + data.amount

    db.add(models.LedgerEntry(
        account_id=sender.id, amount=-data.amount,
        kind="transfer_out", transfer_ref=idempotency_key,
    ))
    db.add(models.LedgerEntry(
        account_id=receiver.id, amount=data.amount,
        kind="transfer_in", transfer_ref=idempotency_key,
    ))

    result = {
        "from_balance": str(sender.balance),
        "to_balance": str(receiver.balance),
    }
    record.response = result
    db.commit()
    return result