import csv
import math
from collections import defaultdict

def wilson_interval(k, n, confidence=0.95):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    z = 1.96  # 95% confidence level
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) / n) + z**2 / (4 * n**2)) / denominator
    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)
    return lower * 100, upper * 100

def generate():
    repos = defaultdict(lambda: {
        'total': 0, 'baseline_fail': 0, 'invalid': 0, 
        'scored': 0, 'killed': 0, 'survived': 0
    })
    categories = defaultdict(lambda: {'scored': 0, 'killed': 0, 'survived': 0})
    operators = defaultdict(lambda: {'category': '', 'scored': 0, 'killed': 0, 'survived': 0})
    survival_reasons = defaultdict(lambda: defaultdict(int))

    with open('batch_results/master.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            repo = row['repo_name']
            status = row['test_status']
            op = row['operator_id']
            cat = row['operator_category']
            reason = row['survival_reason']

            repos[repo]['total'] += 1
            if status == 'baseline_fail':
                repos[repo]['baseline_fail'] += 1
            elif status == 'invalid':
                repos[repo]['invalid'] += 1
            else:
                repos[repo]['scored'] += 1
                operators[op]['category'] = cat
                operators[op]['scored'] += 1
                categories[cat]['scored'] += 1

                if status in ('killed_assert', 'killed_error'):
                    repos[repo]['killed'] += 1
                    operators[op]['killed'] += 1
                    categories[cat]['killed'] += 1
                elif status == 'survived':
                    repos[repo]['survived'] += 1
                    operators[op]['survived'] += 1
                    categories[cat]['survived'] += 1
                    survival_reasons[cat][reason] += 1

    # Include repos with 0 rows that were clean (hardcoded from check)
    all_repos = [
        'aws-platform-starter',
        'aws-terraform-infrastructure',
        'cloud-native-deployment-platform',
        'conf-data-processing-architecture-reference',
        'eks-vulnerable-infra',
        'genai-idp-terraform',
        'platform-design',
        'platform-tools',
        'psoxy',
        'server-terraform',
        'serverless-architecture-patterns',
        'terraform-aws-compliance',
        'terraform-aws-lb',
        'terraform-aws-oidc-github',
        'terraform-aws-security-group',
        'terraform-aws-sonarqube',
        'terraform-aws-static-site',
        'terraform-aws-vpc',
        'terraform-datadog-users',
        'terraform-duplocloud-components',
        'terraform-mongodbatlas-project',
        'terraform-postgres-config-dbs-users-roles',
        'tofu-modules'
    ]

    print("## 1. Aggregate and Category-Level Scores")
    print("| Category | Scored Mutants (n) | Killed (k) | Mutation Score | 95% Wilson CI |")
    print("|---|:---:|:---:|:---:|:---:|")
    # Overall
    total_scored = sum(c['scored'] for c in categories.values())
    total_killed = sum(c['killed'] for c in categories.values())
    overall_p = (total_killed / total_scored) * 100 if total_scored else 0.0
    ol, ou = wilson_interval(total_killed, total_scored)
    print(f"| **Overall** | **{total_scored}** | **{total_killed}** | **{overall_p:.1f}%** | **[{ol:.1f}%, {ou:.1f}%]** |")
    # By Category
    for cat in sorted(categories.keys()):
        c = categories[cat]
        p = (c['killed'] / c['scored']) * 100 if c['scored'] else 0.0
        l, u = wilson_interval(c['killed'], c['scored'])
        print(f"| {cat.capitalize()} | {c['scored']} | {c['killed']} | {p:.1f}% | [{l:.1f}%, {u:.1f}%] |")

    print("\n## 2. Survived-Mutant Classification Breakdown")
    print("| Category | Total Survived | no_coverage | weak_assertion | plan_only_no_assert |")
    print("|---|:---:|:---:|:---:|:---:|")
    for cat in sorted(categories.keys()):
        total_s = categories[cat]['survived']
        nc = survival_reasons[cat]['no_coverage']
        wa = survival_reasons[cat]['weak_assertion']
        po = survival_reasons[cat]['plan_only_no_assert']
        print(f"| {cat.capitalize()} | {total_s} | {nc} | {wa} | {po} |")

    print("\n## 3. Operator-Level Scores")
    print("| Operator ID | Category | Scored (n) | Killed (k) | Mutation Score | 95% Wilson CI |")
    print("|---|---|:---:|:---:|:---:|:---:|")
    for op in sorted(operators.keys()):
        o = operators[op]
        p = (o['killed'] / o['scored']) * 100 if o['scored'] else 0.0
        l, u = wilson_interval(o['killed'], o['scored'])
        print(f"| `{op}` | {o['category']} | {o['scored']} | {o['killed']} | {p:.1f}% | [{l:.1f}%, {u:.1f}%] |")

    print("\n## 4. Per-Repository Scores")
    print("| Repository | Total Mutants | Baseline Fail | Invalid | Scored (n) | Killed (k) | Mutation Score | 95% Wilson CI |")
    print("|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
    for r in sorted(all_repos):
        stats = repos[r]
        p = (stats['killed'] / stats['scored']) * 100 if stats['scored'] else 0.0
        l, u = wilson_interval(stats['killed'], stats['scored'])
        ci_str = f"[{l:.1f}%, {u:.1f}%]" if stats['scored'] else "n/a"
        score_str = f"{p:.1f}%" if stats['scored'] else "n/a"
        print(f"| `{r}` | {stats['total']} | {stats['baseline_fail']} | {stats['invalid']} | {stats['scored']} | {stats['killed']} | {score_str} | {ci_str} |")

if __name__ == '__main__':
    generate()
