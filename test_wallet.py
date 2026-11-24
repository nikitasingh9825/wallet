import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient

from main import app, auth_limiter


def new_client():
    return TestClient(app)


def register_and_login(client, email="a@example.com", password="password123"):
    client.post("/auth/register", json={"email": email, "password": password})
    r = client.post("/auth/login", data={"username": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_account(client, headers, name="main", deposit=None):
    acc = client.post("/accounts", json={"name": name}, headers=headers).json()["id"]
    if deposit:
        client.post(f"/accounts/{acc}/deposit", json={"amount": deposit}, headers=headers)
    return acc


def balance(client, headers, acc):
    return Decimal(client.get(f"/accounts/{acc}", headers=headers).json()["balance"])


def transfer(client, headers, src, dst, amount, key=None):
    return client.post(
        "/transfer",
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json={"from_id": src, "to_id": dst, "amount": amount},
    )




def test_register_and_login():
    client = new_client()
    headers = register_and_login(client)
    assert client.get("/accounts", headers=headers).status_code == 200


def test_duplicate_email_rejected():
    client = new_client()
    body = {"email": "a@example.com", "password": "password123"}
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409


def test_wrong_password_rejected():
    client = new_client()
    register_and_login(client)
    r = client.post("/auth/login", data={"username": "a@example.com", "password": "wrongpass1"})
    assert r.status_code == 401


def test_endpoints_require_token():
    client = new_client()
    assert client.get("/accounts").status_code == 401
    assert client.post("/accounts", json={"name": "x"}).status_code == 401
    assert client.post("/transfer", json={"from_id": 1, "to_id": 2, "amount": 1}).status_code in (401, 422)


def test_login_is_rate_limited():
    auth_limiter.hits.clear()
    auth_limiter.enabled = True
    try:
        client = new_client()
        codes = [
            client.post("/auth/login", data={"username": "x@example.com", "password": "wrongpass1"}).status_code
            for _ in range(12)
        ]
    finally:
        auth_limiter.enabled = False
        auth_limiter.hits.clear()
    assert 429 in codes




def test_cannot_see_other_users_account():
    client = new_client()
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    acc = make_account(client, alice, deposit=100)
    assert client.get(f"/accounts/{acc}", headers=bob).status_code == 404
    assert client.get(f"/accounts/{acc}/ledger", headers=bob).status_code == 404


def test_cannot_withdraw_from_other_users_account():
    client = new_client()
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    acc = make_account(client, alice, deposit=100)
    r = client.post(f"/accounts/{acc}/withdraw", json={"amount": 50}, headers=bob)
    assert r.status_code == 404
    assert balance(client, alice, acc) == Decimal("100")


def test_cannot_transfer_from_other_users_account():
    client = new_client()
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    a = make_account(client, alice, deposit=100)
    b = make_account(client, bob)
    assert transfer(client, bob, a, b, 50).status_code == 404
    assert balance(client, alice, a) == Decimal("100")


def test_can_transfer_to_another_users_account():
    client = new_client()
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    a = make_account(client, alice, deposit=1000)
    b = make_account(client, bob, deposit=200)
    assert transfer(client, alice, a, b, 300).status_code == 200
    assert balance(client, alice, a) == Decimal("700")
    assert balance(client, bob, b) == Decimal("500")




def test_deposit_and_withdraw():
    client = new_client()
    h = register_and_login(client)
    acc = make_account(client, h, deposit=1000)
    client.post(f"/accounts/{acc}/withdraw", json={"amount": 300}, headers=h)
    assert balance(client, h, acc) == Decimal("700")


def test_withdraw_more_than_balance_fails():
    client = new_client()
    h = register_and_login(client)
    acc = make_account(client, h, deposit=100)
    r = client.post(f"/accounts/{acc}/withdraw", json={"amount": 500}, headers=h)
    assert r.status_code == 400
    assert balance(client, h, acc) == Decimal("100")


def test_invalid_amounts_rejected():
    client = new_client()
    h = register_and_login(client)
    acc = make_account(client, h)
    for bad in (-50, 0, 1000001, 10.123):
        r = client.post(f"/accounts/{acc}/deposit", json={"amount": bad}, headers=h)
        assert r.status_code == 422, bad




def test_concurrent_withdrawals_only_one_succeeds():
    client = new_client()
    h = register_and_login(client)
    acc = make_account(client, h, deposit=1000)

    def withdraw(_):
        return new_client().post(
            f"/accounts/{acc}/withdraw", json={"amount": 800}, headers=h
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(withdraw, range(10)))

    assert codes.count(200) == 1
    assert balance(client, h, acc) == Decimal("200")


def test_opposite_transfers_do_not_deadlock():
    client = new_client()
    h = register_and_login(client)
    a = make_account(client, h, "a", deposit=100000)
    b = make_account(client, h, "b", deposit=100000)

    def move(args):
        src, dst = args
        return transfer(new_client(), h, src, dst, 1).status_code

    jobs = [(a, b)] * 50 + [(b, a)] * 50
    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(move, jobs))

    assert codes.count(200) == 100
    assert balance(client, h, a) + balance(client, h, b) == Decimal("200000")




def test_same_idempotency_key_moves_money_once():
    client = new_client()
    h = register_and_login(client)
    a = make_account(client, h, "a", deposit=1000)
    b = make_account(client, h, "b")
    key = str(uuid.uuid4())

    def send(_):
        return transfer(new_client(), h, a, b, 100, key=key).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = list(pool.map(send, range(5)))

    assert all(code == 200 for code in codes)
    assert balance(client, h, a) == Decimal("900")
    assert balance(client, h, b) == Decimal("100")


def test_reused_key_with_different_amount_rejected():
    client = new_client()
    h = register_and_login(client)
    a = make_account(client, h, "a", deposit=1000)
    b = make_account(client, h, "b")
    key = str(uuid.uuid4())
    assert transfer(client, h, a, b, 100, key=key).status_code == 200
    assert transfer(client, h, a, b, 500, key=key).status_code == 422
    assert balance(client, h, a) == Decimal("900")


def test_idempotency_keys_are_per_user():
    client = new_client()
    alice = register_and_login(client, "alice@example.com")
    bob = register_and_login(client, "bob@example.com")
    a = make_account(client, alice, deposit=1000)
    b = make_account(client, bob, deposit=1000)
    key = "shared-key-12345"
    assert transfer(client, alice, a, b, 100, key=key).status_code == 200
    assert transfer(client, bob, b, a, 50, key=key).status_code == 200
    assert balance(client, alice, a) == Decimal("950")
    assert balance(client, bob, b) == Decimal("1050")


# ---------- ledger ----------

def test_ledger_sum_matches_balance():
    client = new_client()
    h = register_and_login(client)
    a = make_account(client, h, "a", deposit=1000)
    b = make_account(client, h, "b", deposit=500)
    client.post(f"/accounts/{a}/withdraw", json={"amount": 100}, headers=h)
    transfer(client, h, a, b, 250)

    for acc in (a, b):
        entries = client.get(f"/accounts/{acc}/ledger", headers=h).json()
        assert sum(Decimal(e["amount"]) for e in entries) == balance(client, h, acc)