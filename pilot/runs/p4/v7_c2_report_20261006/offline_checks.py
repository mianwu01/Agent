"""Complete mechanical/DB evidence without credentials or new model calls."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import c2 as c


def run(workers=32):
    """Save programmatic checks for every historical label input; no model judgment."""
    directory = c.D["step2"]
    manifest = c.read(directory / "manifest.json")
    tasks = c.read(directory / "tasks.json")

    def check(inp):
        path = directory / "programmatic_checks" / f"{inp['digest']}.json"
        if path.exists():
            return c.read(path)
        cached = directory / "mapped_labels" / f"{inp['digest']}.json"
        if cached.exists():
            label = c.read(cached)
            result = {
                "digest": inp["digest"],
                "mechanical_violations": label["mechanical_violations"],
                "fact_check": label["fact_check"],
                "programmatic_scenario_violations": label[
                    "programmatic_scenario_violations"
                ],
                "scenario_judgment_available": True,
                "style_judgment_available": True,
            }
        else:
            data = c.read(directory / "label_inputs" / f"{inp['digest']}.json")
            task = c.x.b.Task.model_validate(tasks[data["task_id"]])
            before = c.mech.replay(task.model_dump(mode="json"), data["prefix"])
            after = c.mech.replay(
                task.model_dump(mode="json"), data["prefix"] + data["block"]
            )
            mechanical = c.mechanical_check(
                task, data["prefix"], data["block"], before, after
            )
            facts = c.mech.check_claims(
                data["prefix"], data["block"], after.environment, before.environment
            )
            result = {
                "digest": inp["digest"],
                "mechanical_violations": mechanical,
                "fact_check": facts,
                "programmatic_scenario_violations": c.programmatic_scenario_violations(
                    facts
                ),
                "scenario_judgment_available": False,
                "style_judgment_available": False,
            }
        c.save(path, result)
        return result

    result = []
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fs = {pool.submit(check, inp): inp for inp in manifest["unique_label_inputs"]}
        for n, future in enumerate(as_completed(fs), 1):
            try:
                result.append(future.result())
            except Exception as exc:
                inp = fs[future]
                errors.append(
                    {
                        "digest": inp["digest"],
                        "type": type(exc).__name__,
                        "error": str(exc)[:2000],
                    }
                )
                c.save(
                    directory / "programmatic_errors" / f"{inp['digest']}.json",
                    errors[-1],
                )
            if n % 500 == 0:
                print("OFFLINE", n, "/", len(fs), "errors", len(errors), flush=True)
    c.save(
        directory / "programmatic_summary.json",
        {
            "unique_inputs": len(manifest["unique_label_inputs"]),
            "completed_checks": len(result),
            "errors": errors,
            "mechanical_invalid_inputs": sum(
                bool(r["mechanical_violations"]) for r in result
            ),
            "programmatic_DB_mismatch_inputs": sum(
                bool(r["programmatic_scenario_violations"]) for r in result
            ),
            "unparsed_scenario_and_style_pending": sum(
                not r["scenario_judgment_available"] for r in result
            ),
            "new_model_calls": 0,
        },
    )


if __name__ == "__main__":
    run()
