"""Report verified cases per provider-configured dollar, preserving task clustering."""

import collections
import importlib
import json
import random
import sqlite3
import sys

from p4_cost_control_run import HISTORICAL, NEW


def quantiles(values):
    values = sorted(values)
    return (
        [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]
        if values
        else None
    )


def main():
    ledger = NEW / "costs.sqlite"
    calls = []
    if ledger.exists():
        with sqlite3.connect(ledger) as db:
            db.row_factory = sqlite3.Row
            calls = [
                dict(r)
                for r in db.execute(
                    "SELECT *,COALESCE(charged,reserved) AS usd FROM calls"
                )
            ]
    arms = {}
    if any(
        (NEW / "step3/arms" / arm).exists() for arm in ["A0", "A1", "A2", "A3", "A4"]
    ):
        sys.path.insert(0, str(HISTORICAL))
        analysis = importlib.import_module("analyze")
        analysis.c.D["step3"] = NEW / "step3"
        arms = analysis.search_summary()
    result = {
        "currency": "USD at configured provider rates",
        "new_api_calls": 0,
        "arms": {},
        "incomplete_comparison": True,
    }
    lines = [
        "# 节省开销后的搜索比较",
        "",
        "|臂|完成|已知费用 USD|未知用量预留 USD|有效 distinct/USD|规则内 distinct/USD|",
        "|---|---|---|---|---|---|",
    ]
    for arm in ["A0", "A1", "A2", "A3", "A4"]:
        rows = [r for r in calls if r["arm"] == arm]
        known = sum(r["usd"] for r in rows if r["status"] == "response")
        unknown = sum(r["usd"] for r in rows if r["status"] != "response")
        total = known + unknown
        state = arms.get(arm, {})
        run_status = NEW / f"{arm}_run_status.json"
        complete = (
            bool(state.get("complete"))
            and run_status.exists()
            and json.loads(run_status.read_text()).get("complete", False)
        )
        cells = state.get("distinct_cells", [])
        roots = NEW / "step3/arms" / arm
        tasks = (
            sorted(json.loads((roots / "tasks.json").read_text()))
            if (roots / "tasks.json").exists()
            else []
        )
        cost_by_task = collections.Counter()
        for row in rows:
            if row["task_id"]:
                cost_by_task[row["task_id"]] += row["usd"]
        shared = total - sum(cost_by_task.values())
        scopes = {}
        cumulative = {}
        for scope in ["all_valid", "in_rule"]:
            selected = [
                c
                for c in cells
                if scope == "all_valid"
                or any(e["style"] == "in_rule" for e in c["evidence"])
            ]
            counts = collections.Counter(c["task_id"] for c in selected)
            by_class = collections.Counter(c["class"] for c in selected)
            class_counts = {
                cls: collections.Counter(
                    c["task_id"] for c in selected if c["class"] == cls
                )
                for cls in by_class
            }
            boot = []
            class_boot = collections.defaultdict(list)
            rng = random.Random(2026100801)
            for _ in range(1000):
                picked = rng.choices(tasks, k=len(tasks))
                den = sum(cost_by_task[t] for t in picked) + shared
                if den:
                    boot.append(sum(counts[t] for t in picked) / den)
                    for cls, values in class_counts.items():
                        class_boot[cls].append(sum(values[t] for t in picked) / den)
            scopes[scope] = {
                "distinct": len(selected),
                "per_usd": len(selected) / total if total else None,
                "task_cluster95_CI": quantiles(boot),
                "by_class": {
                    cls: {
                        "distinct": n,
                        "per_usd": n / total if total else None,
                        "task_cluster95_CI": quantiles(class_boot[cls]),
                    }
                    for cls, n in by_class.items()
                },
            }
            confirmations = []
            for cell in selected:
                paths = [
                    roots / "verified" / f"{e['case']}.json" for e in cell["evidence"]
                ]
                times = [p.stat().st_mtime for p in paths if p.exists()]
                if times:
                    confirmations.append(min(times))
            cumulative[scope] = [
                {
                    "confirmed_distinct": i + 1,
                    "confirmed_at": when,
                    "usd": sum(
                        r["usd"]
                        for r in rows
                        if (r["finished"] or r["started"]) <= when
                    ),
                }
                for i, when in enumerate(sorted(confirmations))
            ]
        result["arms"][arm] = {
            "complete": complete,
            "known_usd": known,
            "unknown_reserved_usd": unknown,
            "scopes": scopes,
            "cumulative_cases_vs_usd": cumulative,
            "screening_to_retest_survival_rate": state.get("retest_survival_rate"),
            "cost_by_task": dict(cost_by_task),
            "shared_cost_usd": shared,
        }
        lines.append(
            f"|{arm}|{complete}|{known:.6f}|{unknown:.6f}|{scopes['all_valid']['per_usd']}|{scopes['in_rule']['per_usd']}|"
        )
    result["incomplete_comparison"] = not all(
        r["complete"] for r in result["arms"].values()
    )
    (NEW / "dollar_comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    lines += [
        "",
        "未完成臂不用于方法优劣排名。未知用量按原预留保守计入；USD金额来自填写的服务商费率，不冒充实际扣款流水。所有confirmed-case分类和M3去重沿用历史定义。",
        "",
        "抽样验证输入减少 "
        + f"{json.loads((NEW / 'offline_savings.json').read_text()).get('input_byte_reduction_fraction', 0):.1%}"
        + " UTF-8字节；精简输入与Luna判决验证尚未调用模型，未切换正式筛选。",
    ]
    (NEW / "dollar_report.md").write_text("\n".join(lines) + "\n")
    print("Dollar report saved; no API calls")


if __name__ == "__main__":
    main()
