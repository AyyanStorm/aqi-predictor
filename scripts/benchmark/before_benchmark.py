#!/usr/bin/env python3
"""
before_benchmark.py — measure warm latency (median/p95) of the live Render
deployment. Read-only: only GET requests. Q5 rule: Render is the source of
truth; cold start recorded separately, NOT part of primary gates.
"""
import json
import statistics
import subprocess
import sys
import time

BASE = "https://aqi-api-r0hg.onrender.com"
DASH = "https://aqi-predictor-blii.onrender.com"

ENDPOINTS = [
    ("api /health", f"{BASE}/health"),
    ("api /cities", f"{BASE}/cities"),
    ("api /predict (Karachi)", f"{BASE}/predict?lat=24.8608&lon=67.0104&city=Karachi"),
    ("dashboard root", f"{DASH}/"),
]

N_WARM = 7
TIMEOUT = 90  # generous: first call may be a cold start


def time_get(url):
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(TIMEOUT), url],
            capture_output=True, text=True, timeout=TIMEOUT + 10,
        )
        code = r.stdout.strip()
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    return (time.perf_counter() - t0), code


def main():
    results = {}
    for name, url in ENDPOINTS:
        print(f"\n=== {name} ===")
        # 1. cold-start probe (recorded separately, out of primary scope)
        cold, code = time_get(url)
        print(f"  cold-start probe: {cold:.2f}s (http {code}) — recorded, out of scope")

        # 2. warm-up: let the instance settle after cold start
        time.sleep(2)
        time_get(url)

        # 3. warm measurements
        latencies = []
        for i in range(N_WARM):
            t, code = time_get(url)
            if t is None:
                latencies.append(float("nan"))
                print(f"  warm #{i+1}: TIMEOUT")
            else:
                latencies.append(t)
                print(f"  warm #{i+1}: {t:.2f}s (http {code})")
            time.sleep(0.5)

        clean = [t for t in latencies if not (t != t)]
        if clean:
            results[name] = {
                "median_s": round(statistics.median(clean), 2),
                "p95_s": round(sorted(clean)[int(len(clean) * 0.95) - 1], 2),
                "min_s": round(min(clean), 2),
                "max_s": round(max(clean), 2),
                "n": len(clean),
                "cold_start_s": round(cold, 2) if cold is not None else None,
                "http": code,
            }
        else:
            results[name] = {"error": "all warm calls timed out"}

    print("\n\n===== BEFORE BENCHMARK SUMMARY =====")
    print(json.dumps(results, indent=2))
    with open("logs/before_benchmark.json", "w") as f:
        json.dump(results, f, indent=2)
    print("saved -> logs/before_benchmark.json")


if __name__ == "__main__":
    sys.exit(main())
