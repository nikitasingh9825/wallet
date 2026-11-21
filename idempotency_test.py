import threading
import uuid
import requests

BASE = "http://127.0.0.1:8000"

a = requests.post(f"{BASE}/accounts", json={"owner": "A"}).json()["id"]
b = requests.post(f"{BASE}/accounts", json={"owner": "B"}).json()["id"]
requests.post(f"{BASE}/accounts/{a}/deposit", json={"amount": 1000})

key = str(uuid.uuid4())
results = []


def send():
    r = requests.post(
        f"{BASE}/transfer",
        headers={"Idempotency-Key": key},
        json={"from_id": a, "to_id": b, "amount": 100},
    )
    results.append(r.status_code)


threads = [threading.Thread(target=send) for _ in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()

print("statuses:", results)
print("A balance:", requests.get(f"{BASE}/accounts/{a}").json()["balance"])
print("B balance:", requests.get(f"{BASE}/accounts/{b}").json()["balance"])