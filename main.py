import time
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