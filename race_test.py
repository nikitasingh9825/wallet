import threading
import requests

BASE = "http://127.0.0.1:8000"

acc = requests.post(f"{BASE}/accounts", json={"owner": "RaceTest"}).json()
acc_id = acc["id"]
requests.post(f"{BASE}/accounts/{acc_id}/deposit", json={"amount": 1000})

results = []

def withdraw():
    r = requests.post(f"{BASE}/accounts/{acc_id}/withdraw", json={"amount": 800})
    results.append(r.status_code)

threads = [threading.Thread(target=withdraw) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()

final = requests.get(f"{BASE}/accounts/{acc_id}").json()
print("successes:", results.count(200))
print("failures:", results.count(400))
print("final balance:", final["balance"])