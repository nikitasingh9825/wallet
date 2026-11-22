import threading
import uuid
import requests

BASE = "http://127.0.0.1:8000"

a = requests.post(f"{BASE}/accounts", json={"owner": "A"}).json()["id"]
b = requests.post(f"{BASE}/accounts", json={"owner": "B"}).json()["id"]
requests.post(f"{BASE}/accounts/{a}/deposit", json={"amount": 100000})
requests.post(f"{BASE}/accounts/{b}/deposit", json={"amount": 100000})

results = []


def move(src, dst):
    for _ in range(50):
        r = requests.post(
            f"{BASE}/transfer",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"from_id": src, "to_id": dst, "amount": 1},
        )
        results.append(r.status_code)


t1 = threading.Thread(target=move, args=(a, b))
t2 = threading.Thread(target=move, args=(b, a))
t1.start()
t2.start()
t1.join()
t2.join()

total = sum(
    float(requests.get(f"{BASE}/accounts/{i}").json()["balance"]) for i in (a, b)
)
print("requests sent:", len(results))
print("ok:", results.count(200))
print("errors:", len(results) - results.count(200))
print("total:", total)