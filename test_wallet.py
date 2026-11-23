import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient

from main import app


def new_client():
    return TestClient(app)


def make_account(client, owner="test", deposit=None):
    account_id = client.post("/accounts", json={"owner": owner}).json()["id"]
    if deposit:
        client.post(f"/accounts/{account_id}/deposit", json={"amount": deposit})
    return account_id


def balance(client, account_id):
    return Decimal(str(client.get(f"/accounts/{account_id}").json()["balance"]))


def transfer(client, src, dst, amount, key=None):
    return client.post(
        "/transfer",
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
        json={"from_id": src, "to_id": dst, "amount": amount},
    )


def test_deposit_and_withdraw():
    client = new_client()
    acc = make_account(client, deposit=1000)
    client.post(f"/accounts/{acc}/withdraw", json={"amount": 300})
    assert balance(client, acc) == Decimal("700")


def test_withdraw_more_than_balance_fails():
    client = new_client()
    acc = make_account(client, deposit=100)
    r = client.post(f"/accounts/{acc}/withdraw", json={"amount": 500})
    assert r.status_code == 400
    assert balance(client, acc) == Decimal("100")


def test_negative_amount_rejected():
    client = new_client()
    acc = make_account(client)
    r = client.post(f"/accounts/{acc}/deposit", json={"amount": -50})
    assert r.status_code == 422


def test_transfer_keeps_total_constant():
    client = new_client()
    a = make_account(client, deposit=1000)
    b = make_account(client, deposit=200)
    assert transfer(client, a, b, 300).status_code == 200
    assert balance(client, a) == Decimal("700")
    assert balance(client, b) == Decimal("500")


def test_concurrent_withdrawals_only_one_succeeds():
    client = new_client()
    acc = make_account(client, deposit=1000)

    def withdraw(_):
        c = new_client()
        return c.post(f"/accounts/{acc}/withdraw", json={"amount": 800}).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(withdraw, range(10)))

    assert codes.count(200) == 1
    assert balance(client, acc) == Decimal("200")


def test_opposite_transfers_do_not_deadlock():
    client = new_client()
    a = make_account(client, deposit=100000)
    b = make_account(client, deposit=100000)

    def move(args):
        src, dst = args
        c = new_client()
        return transfer(c, src, dst, 1).status_code

    jobs = [(a, b)] * 50 + [(b, a)] * 50
    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(move, jobs))

    assert codes.count(200) == 100
    assert balance(client, a) + balance(client, b) == Decimal("200000")


def test_same_idempotency_key_moves_money_once():
    client = new_client()
    a = make_account(client, deposit=1000)
    b = make_account(client)
    key = str(uuid.uuid4())

    def send(_):
        c = new_client()
        return transfer(c, a, b, 100, key=key).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = list(pool.map(send, range(5)))

    assert all(code == 200 for code in codes)
    assert balance(client, a) == Decimal("900")
    assert balance(client, b) == Decimal("100")


def test_ledger_sum_matches_balance():
    client = new_client()
    a = make_account(client, deposit=1000)
    b = make_account(client, deposit=500)
    client.post(f"/accounts/{a}/withdraw", json={"amount": 100})
    transfer(client, a, b, 250)

    for acc in (a, b):
        entries = client.get(f"/accounts/{acc}/ledger").json()
        ledger_sum = sum(Decimal(e["amount"]) for e in entries)
        assert ledger_sum == balance(client, acc)