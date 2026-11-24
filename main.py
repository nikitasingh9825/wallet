import hashlib
from decimal import Decimal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from ratelimit import RateLimiter
from security import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
import models

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Wallet API")

MAX_AMOUNT = Decimal("1000000")
auth_limiter = RateLimiter(limit=10, window_seconds=60)
money_limiter = RateLimiter(limit=60, window_seconds=60)


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=100)
    password: str = Field(min_length=8, max_length=64)


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class Amount(BaseModel):
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2)


class Transfer(BaseModel):
    from_id: int
    to_id: int
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2)


def get_account_or_404(db: Session, account_id: int, user=None, lock: bool = False):
    account = db.get(models.Account, account_id, with_for_update=lock)
    if account is None or (user is not None and account.user_id != user.id):
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def account_json(account):
    return {"id": account.id, "name": account.name, "balance": str(account.balance)}


@app.post("/auth/register", status_code=201, dependencies=[Depends(auth_limiter)])
def register(data: UserCreate, db: Session = Depends(get_db)):
    user = models.User(
        email=data.email.lower(), password_hash=hash_password(data.password)
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return {"id": user.id, "email": user.email}


@app.post("/auth/login", dependencies=[Depends(auth_limiter)])
def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = db.query(models.User).filter_by(email=form.username.lower()).first()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return {"access_token": create_token(user.id), "token_type": "bearer"}


@app.post("/accounts", status_code=201)
def create_account(
    data: AccountCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = models.Account(user_id=user.id, name=data.name, balance=0)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_json(account)


@app.get("/accounts")
def list_accounts(user=Depends(get_current_user), db: Session = Depends(get_db)):
    accounts = (
        db.query(models.Account)
        .filter_by(user_id=user.id)
        .order_by(models.Account.id)
        .all()
    )
    return [account_json(a) for a in accounts]


@app.get("/accounts/{account_id}")
def get_account(
    account_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    return account_json(get_account_or_404(db, account_id, user=user))


@app.get("/accounts/{account_id}/ledger")
def get_ledger(
    account_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    get_account_or_404(db, account_id, user=user)
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


@app.post("/accounts/{account_id}/deposit", dependencies=[Depends(money_limiter)])
def deposit(
    account_id: int,
    data: Amount,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = get_account_or_404(db, account_id, user=user, lock=True)
    account.balance = account.balance + data.amount
    db.add(models.LedgerEntry(account_id=account.id, amount=data.amount, kind="deposit"))
    db.commit()
    return {"id": account.id, "balance": str(account.balance)}


@app.post("/accounts/{account_id}/withdraw", dependencies=[Depends(money_limiter)])
def withdraw(
    account_id: int,
    data: Amount,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = get_account_or_404(db, account_id, user=user, lock=True)
    if account.balance < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")
    account.balance = account.balance - data.amount
    db.add(models.LedgerEntry(account_id=account.id, amount=-data.amount, kind="withdraw"))
    db.commit()
    return {"id": account.id, "balance": str(account.balance)}


@app.post("/transfer", dependencies=[Depends(money_limiter)])
def transfer(
    data: Transfer,
    idempotency_key: str = Header(..., min_length=8, max_length=100),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.from_id == data.to_id:
        raise HTTPException(status_code=400, detail="Cannot transfer to the same account")

    # Keys are scoped to the user, so two users can never collide.
    scoped_key = f"{user.id}:{idempotency_key}"
    request_hash = hashlib.sha256(
        f"{data.from_id}:{data.to_id}:{data.amount:.2f}".encode()
    ).hexdigest()

    record = models.IdempotencyKey(
        key=scoped_key, request_hash=request_hash, response=None
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        saved = db.get(models.IdempotencyKey, scoped_key)
        if saved is None:
            raise HTTPException(status_code=409, detail="Please retry")
        if saved.request_hash != request_hash:
            raise HTTPException(
                status_code=422,
                detail="Idempotency key was already used for a different request",
            )
        return saved.response

    # Lock in id order to avoid deadlocks.
    first_id, second_id = sorted([data.from_id, data.to_id])
    first = get_account_or_404(db, first_id, lock=True)
    second = get_account_or_404(db, second_id, lock=True)

    sender = first if first.id == data.from_id else second
    receiver = second if sender is first else first

    if sender.user_id != user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    if sender.balance < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    sender.balance = sender.balance - data.amount
    receiver.balance = receiver.balance + data.amount

    db.add(models.LedgerEntry(
        account_id=sender.id, amount=-data.amount,
        kind="transfer_out", transfer_ref=scoped_key,
    ))
    db.add(models.LedgerEntry(
        account_id=receiver.id, amount=data.amount,
        kind="transfer_in", transfer_ref=scoped_key,
    ))

    result = {
        "from_balance": str(sender.balance),
        "to_balance": str(receiver.balance),
    }
    record.response = result
    db.commit()
    return result