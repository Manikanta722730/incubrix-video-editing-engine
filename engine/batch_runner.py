"""Batch Runner Command-Line Tool.

Integration Standard 10:
A command-line tool that runs a folder or file of test inputs against the API
and writes all results to one folder.
"""

from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time
from typing import Dict, Any, List

from engine.session_runner import run_session_file
from engine.manifest import generate_manifest, write_manifest_file


def run_batch(input_path: str, output_dir: str, api_url: str = "") -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    session_files = []

    if os.path.isdir(input_path):
        session_files = sorted(glob.glob(os.path.join(input_path, "*.yaml")) + glob.glob(os.path.join(input_path, "*.yml")))
    elif os.path.isfile(input_path):
        session_files = [input_path]
    else:
        print(f"Error: input path '{input_path}' not found", file=sys.stderr)
        return {"error": f"Path not found: {input_path}"}

    print(f"Starting IncuBrix Batch Runner: Found {len(session_files)} session file(s).")
    batch_results = []
    total_start = time.time()

    for idx, sfile in enumerate(session_files):
        base_name = os.path.splitext(os.path.basename(sfile))[0]
        session_out = os.path.join(output_dir, base_name)
        os.makedirs(session_out, exist_ok=True)

        print(f"[{idx+1}/{len(session_files)}] Running {os.path.basename(sfile)} -> {session_out}...")
        t0 = time.time()
        try:
            res = run_session_file(sfile, session_out)
            elapsed = time.time() - t0

            # Generate manifest
            manifest = generate_manifest(
                job_id=f"batch_{base_name}",
                timeline_id=res["final_timeline_hash"][:16],
                source_media_duration_s=res.get("steps", [{}])[-1].get("duration_s", 240.0),
                rendered_duration_s=res["final_duration_s"],
                timings={"total": round(elapsed, 4)}
            )
            write_manifest_file(manifest, os.path.join(session_out, "manifest.json"))

            batch_results.append({
                "file": sfile,
                "status": "succeeded",
                "total_steps": res["total_steps"],
                "final_timeline_hash": res["final_timeline_hash"],
                "final_duration_s": res["final_duration_s"],
                "elapsed_s": round(elapsed, 4)
            })
        except Exception as e:
            elapsed = time.time() - t0
            print(f"Failed {sfile}: {e}", file=sys.stderr)
            batch_results.append({
                "file": sfile,
                "status": "failed",
                "error": str(e),
                "elapsed_s": round(elapsed, 4)
            })

    total_time = time.time() - total_start
    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_sessions": len(session_files),
        "succeeded": sum(1 for r in batch_results if r["status"] == "succeeded"),
        "failed": sum(1 for r in batch_results if r["status"] == "failed"),
        "total_elapsed_s": round(total_time, 3),
        "sessions": batch_results
    }

    summary_file = os.path.join(output_dir, "batch_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Batch completed: {summary['succeeded']}/{summary['total_sessions']} succeeded in {summary['total_elapsed_s']}s.")
    print(f"Summary written to: {summary_file}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Batch Session Runner")
    parser.add_argument("--input", "-i", required=True, help="Input directory or session YAML file")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory for all results")
    parser.add_argument("--api-url", default="", help="Optional API URL")
    args = parser.parse_args()

    run_batch(args.input, args.output_dir, args.api_url)


if __name__ == "__main__":
    main()

