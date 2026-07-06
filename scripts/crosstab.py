import csv
from collections import defaultdict

crosstab = defaultdict(lambda: defaultdict(int))
with open('batch_results/master.csv') as f:
    for row in csv.DictReader(f):
        if row['test_status'] == 'survived':
            crosstab[row['operator_id']][row['survival_reason']] += 1

print("| Operator ID | no_coverage | weak_assertion |")
print("|---|:---:|:---:|")
for op in sorted(crosstab.keys()):
    nc = crosstab[op]['no_coverage']
    wa = crosstab[op]['weak_assertion']
    print(f"| `{op}` | {nc} | {wa} |")
