#!/usr/bin/env python3
"""
after_benchmark.py — same protocol as before_benchmark.py, run against the
SAME deployed code after the Wed 19 Aug staged deploy. Q5: Render is the
source of truth; median/p95; cold start recorded separately, out of scope.
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
TIMEOUT = 90


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
        cold, code = time_get(url)
        print(f"  cold-start probe: {cold:.2f}s (http {code}) — recorded, out of scope")
        time.sleep(2)
        time_get(url)
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

    print("\n\n===== AFTER BENCHMARK SUMMARY =====")
    print(json.dumps(results, indent=2))
    with open("logs/after_benchmark.json", "w") as f:
        json.dump(results, f, indent=2)
    print("saved -> logs/after_benchmark.json")


if __name__ == "__main__":
    sys.exit(main())
