"""Repeat the independent-user journeys after fixes; use the isolated QA server."""
import concurrent.futures
import json
import time
from pathlib import Path

from qa_review import user, latencies

start = time.perf_counter()
results, errors = [], []
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    futures = {pool.submit(user, i): i for i in range(20)}
    for future in concurrent.futures.as_completed(futures):
        try:
            results.append(future.result())
        except Exception as exc:
            errors.append({"user": futures[future], "error": str(exc)})
times = sorted(latencies)
report = {"users": 20, "completed": len(results), "errors": errors,
          "requests": len(times), "seconds": round(time.perf_counter() - start, 2),
          "p50_ms": round(times[len(times)//2]), "p95_ms": round(times[int(len(times)*.95)]),
          "max_ms": round(max(times)), "details": results}
Path("qa_fixed_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in report.items() if k != "details"}))
assert not errors and len(results) == 20
