import json

with open(r'd:\HAC_SUST\Preliminary Questions and Resources\SUST_Preli_Sample_Cases.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("ID           | case_type                           | department             | severity | review | verdict            | txn_id")
print("-" * 150)
for c in data['cases']:
    o = c['expected_output']
    sid = c['id']
    ct = o['case_type']
    dept = o['department']
    sev = o['severity']
    rev = str(o['human_review_required'])
    verd = o['evidence_verdict']
    txn = str(o['relevant_transaction_id'])
    print(f"{sid:12s} | {ct:35s} | {dept:22s} | {sev:8s} | {rev:5s} | {verd:18s} | {txn}")

print()
print("=== human_review_required = true cases ===")
for c in data['cases']:
    o = c['expected_output']
    if o['human_review_required']:
        print(f"  {c['id']}: {o['case_type']} / {o['severity']} / {o['department']}")

print()
print("=== human_review_required = false cases ===")
for c in data['cases']:
    o = c['expected_output']
    if not o['human_review_required']:
        print(f"  {c['id']}: {o['case_type']} / {o['severity']} / {o['department']}")
