"""Recompute aggregate tables from completed campaigns, without running load."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def aggregate(paths):
    groups = defaultdict(list)
    campaigns = []
    for path in paths:
        path = Path(path)
        value = json.loads((path/"summary.json").read_text())
        if not value["complete"]:
            raise ValueError(f"Incomplete campaign: {path}")
        campaigns.append({"path": str(path), "elapsed_seconds": value["elapsed_seconds"],
                          "trials": len(value["trials"]),
                          "overflow_reasons": value["overflow_probe"]["summary"]["rejection_reasons"]})
        for trial in value["trials"]:
            events = [json.loads(line) for line in (path/trial["name"]/"events.jsonl").read_text().splitlines()]
            primary_times = [e["mono"] for e in events if e["event"] == "request"][:trial["n"]]
            trial["server_request_spread_seconds"] = max(primary_times)-min(primary_times)
            groups[(trial["case"], trial["seed_policy"], trial["n"], trial["policy"])].append(trial)
    levels = []
    for key, trials in sorted(groups.items()):
        rows = [row for trial in trials for row in trial["rows"]]
        good = [row for row in rows if row["state"] == "succeeded"]
        item = dict(zip(("case", "seed_policy", "n", "policy"), key))
        item.update(repetitions=len(trials), attempts=len(rows),
                    admitted=sum(t["summary"]["admitted"] for t in trials),
                    rejected=sum(t["summary"]["rejected"] for t in trials),
                    engine_calls=sum(t["summary"]["engine_calls"] for t in trials),
                    cache_hits=sum(t["summary"]["cache_hits"] for t in trials),
                    results=len(good),
                    admitted_per_trial=[t["summary"]["admitted"] for t in trials],
                    server_rss_mib_max=max(t["resources"]["server_rss_bytes"] for t in trials)/2**20,
                    controller_rss_mib_max=max(t["resources"]["controller_rss_bytes"] for t in trials)/2**20,
                    client_submit_spread_max=max(t["submit_spread_seconds"] for t in trials),
                    server_request_spread_max=max(t["server_request_spread_seconds"] for t in trials),
                    isolation_verified=all(row.get("isolation_verified") for row in good),
                    duplicates_verified=all(row.get("duplicate_verified") for row in good))
        for metric in ("wait_seconds", "result_seconds", "client_result_seconds"):
            values = [row[metric] for row in good]
            item[metric+"_median"] = statistics.median(values) if values else None
            item[metric+"_max"] = max(values) if values else None
        rejected = [row["response_seconds"] for row in rows if row["state"] == "rejected"]
        item["rejection_response_median"] = statistics.median(rejected) if rejected else None
        item["rejection_response_max"] = max(rejected) if rejected else None
        levels.append(item)
    return {"campaigns": campaigns, "levels": levels}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaigns", nargs="+")
    args = parser.parse_args()
    print(json.dumps(aggregate(args.campaigns), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
