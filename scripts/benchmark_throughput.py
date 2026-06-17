"""
Benchmark ARQ worker throughput for the invoice extraction + scoring pipeline.

For each candidate config, this script:
  1. Resets the DB + MinIO to a clean post-seed state (scripts/reset_db.py)
  2. Runs scripts/upload_clean_invoices.py to enqueue ingest + extraction jobs
     for the full clean invoice dataset — note no worker is running yet, so
     jobs simply pile up in Redis untouched.
  3. Starts the timer, launches N `arq ... --burst` worker processes (each
     exits on its own once the queue, including any jobs `extract_document`
     itself enqueues, is fully drained), and waits for all of them to exit.
  4. Stops the timer and sanity-checks DB row counts against the number of
     files uploaded.

Run each config several times and compare medians.

IMPORTANT: make sure no `make worker` (or any other long-running ARQ worker)
is already running in another terminal — it would steal jobs from the burst
workers being timed here and skew the results.

Prerequisites: `make up` (Postgres/MinIO/Redis), `make seed`, and the FastAPI
dev server (`uvicorn apps.api.main:app --port 8000`) must already be running.
Do NOT also run `make worker`.

Usage:
    source venv/bin/activate
    python scripts/benchmark_throughput.py --rounds 5
    python scripts/benchmark_throughput.py --rounds 5 --configs baseline,scaled,wide
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent))
import reset_db  # noqa: E402

DB_URL = os.getenv("DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight")
DEFAULT_DIR = Path("dataset/generated/invoices_json")
DEFAULT_API = "http://localhost:8000"
RESULTS_FILE = Path("scripts/benchmark_results.json")


@dataclass
class Config:
    name: str
    num_processes: int
    max_jobs: int
    pool_max_size: int

    def env(self) -> dict:
        env = os.environ.copy()
        env["ARQ_MAX_JOBS"] = str(self.max_jobs)
        env["ARQ_DB_POOL_MAX_SIZE"] = str(self.pool_max_size)
        return env


CONFIGS: dict[str, Config] = {
    "baseline": Config("baseline", num_processes=1, max_jobs=10, pool_max_size=10),
    "scaled": Config("scaled", num_processes=1, max_jobs=40, pool_max_size=40),
    "wide": Config("wide", num_processes=4, max_jobs=10, pool_max_size=10),
}


def run_upload(invoice_dir: Path, api_url: str) -> int:
    proc = subprocess.run(
        [sys.executable, "scripts/upload_clean_invoices.py", "--dir", str(invoice_dir), "--api-url", api_url],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        sys.exit("[error] upload script failed")
    for line in proc.stdout.splitlines():
        if line.strip().startswith("Found"):
            print(f"  {line.strip()}")
        if "ingested+enqueued" in line:
            print(f"  {line.strip()}")
    # ok= count tells us how many files actually got enqueued for extraction
    ok_count = 0
    for line in proc.stdout.splitlines():
        if "ok=" in line:
            try:
                ok_count = int(line.split("ok=")[1].split()[0])
            except (IndexError, ValueError):
                pass
    return ok_count


def run_burst_workers(config: Config) -> float:
    t0 = time.monotonic()
    procs = [
        subprocess.Popen(
            ["arq", "apps.api.worker.settings.WorkerSettings", "--burst"],
            env=config.env(),
        )
        for _ in range(config.num_processes)
    ]
    for p in procs:
        p.wait()
    t1 = time.monotonic()
    failed = [p for p in procs if p.returncode != 0]
    if failed:
        print(f"  [warn] {len(failed)} worker process(es) exited non-zero")
    return t1 - t0


def sanity_counts() -> dict:
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM invoices")
        invoices = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM alerts")
        alerts = cur.fetchone()[0]
    return {"invoices": invoices, "alerts": alerts}


def run_trial(config: Config, invoice_dir: Path, api_url: str) -> dict:
    reset_db.reset_db()
    reset_db.reset_minio()

    ok_count = run_upload(invoice_dir, api_url)
    print(f"  enqueued {ok_count} extraction jobs")

    elapsed = run_burst_workers(config)
    counts = sanity_counts()

    if counts["invoices"] != ok_count:
        print(
            f"  [warn] invoices written ({counts['invoices']}) != files enqueued "
            f"({ok_count}) — some extractions may have failed or are still in flight"
        )

    print(f"  elapsed: {elapsed:.1f}s  invoices={counts['invoices']}  alerts={counts['alerts']}")
    return {"elapsed": elapsed, **counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--rounds", type=int, default=5, help="Trials per config (default: 5)")
    parser.add_argument(
        "--configs",
        default="baseline,scaled,wide",
        help=f"Comma-separated config names to test (available: {', '.join(CONFIGS)})",
    )
    args = parser.parse_args()

    config_names = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in config_names if c not in CONFIGS]
    if unknown:
        sys.exit(f"[error] unknown config(s): {unknown} — available: {', '.join(CONFIGS)}")

    all_results: dict[str, list[dict]] = {}
    for name in config_names:
        config = CONFIGS[name]
        print(f"\n=== {name}  (processes={config.num_processes}  max_jobs={config.max_jobs}  pool={config.pool_max_size}) ===")
        trials = []
        for round_num in range(1, args.rounds + 1):
            print(f"-- round {round_num}/{args.rounds} --")
            trials.append(run_trial(config, args.dir, args.api_url))
        all_results[name] = trials

    print("\n=== Summary (median elapsed seconds) ===")
    medians = {}
    for name, trials in all_results.items():
        med = statistics.median(t["elapsed"] for t in trials)
        medians[name] = med
        print(f"  {name:<10} median={med:.1f}s  raw={[round(t['elapsed'], 1) for t in trials]}")

    if "baseline" in medians:
        baseline = medians["baseline"]
        print()
        for name, med in medians.items():
            if name == "baseline":
                continue
            pct = (baseline - med) / baseline * 100
            print(f"  {name} vs baseline: {pct:+.1f}%  ({baseline:.1f}s -> {med:.1f}s)")

    RESULTS_FILE.write_text(json.dumps(all_results, indent=2))
    print(f"\nRaw results written to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
