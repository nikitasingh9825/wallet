from sqlalchemy import text
from database import engine

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT a.id, a.balance, COALESCE(SUM(l.amount), 0) AS ledger_sum
        FROM accounts a
        LEFT JOIN ledger_entries l ON l.account_id = a.id
        GROUP BY a.id, a.balance
        ORDER BY a.id
    """)).fetchall()

bad = [r for r in rows if r.balance != r.ledger_sum]
print("accounts checked:", len(rows))
print("mismatches:", len(bad))
for r in bad:
    print("account", r.id, "balance", r.balance, "ledger sum", r.ledger_sum)