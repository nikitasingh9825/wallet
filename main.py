from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
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


@app.post("/accounts/{account_id}/deposit")
def deposit(account_id: int, data: Amount, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_id, lock=True)
    account.balance = account.balance + data.amount
    db.commit()
    return {"id": account.id, "balance": account.balance}


@app.post("/accounts/{account_id}/withdraw")
def withdraw(account_id: int, data: Amount, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_id, lock=True)
    if account.balance < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")
    account.balance = account.balance - data.amount
    db.commit()
    return {"id": account.id, "balance": account.balance}


@app.post("/transfer")
def transfer(data: Transfer, db: Session = Depends(get_db)):
    if data.from_id == data.to_id:
        raise HTTPException(status_code=400, detail="Cannot transfer to the same account")

    first_id, second_id = sorted([data.from_id, data.to_id])
    first = get_account_or_404(db, first_id, lock=True)
    second = get_account_or_404(db, second_id, lock=True)

    sender = first if first.id == data.from_id else second
    receiver = second if sender is first else first

    if sender.balance < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")
    sender.balance = sender.balance - data.amount
    receiver.balance = receiver.balance + data.amount
    db.commit()
    return {"from_balance": sender.balance, "to_balance": receiver.balance}