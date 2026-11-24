#!/usr/bin/env python3
"""
Downloads all unique camera shots (excluding macOS AppleDouble ._ files and exact ' 2.MOV' duplicates)
plus production stills from the PRECIPICE FILM Google Drive folder using parallel workers.
Resumes cleanly by skipping files that already exist with matching byte size.
"""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "drive_manifest.json"
RAW_DIR = ROOT / "raw"

CAM_FOLDERS = {
    "CHICARA_CAM": "1GMoLU-FXSw_20zusRGMJQmt-fKQ_Lfaw",
    "ROB_CAM": "1ZEx8Yz0XX5slMRY3tGQ1UXvLkONr8xtm",
    "SECRET_CAM": "1U-4LFnuUSUcjA93bCCK0hfaVt5FTmebi",
}


def ls_folder(fid: str) -> list[dict]:
    out = subprocess.check_output(["gdrive", "readonly", "ls", fid, "--max", "0", "--json"], text=True)
    return json.loads(out)


def build_jobs() -> list[dict]:
    jobs: list[dict] = []
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # Add videos (deduplicating exact ' 2.' Finder copies)
    for cam, info in manifest.items():
        vids = info["videos"]
        by_name = {v["name"]: v for v in vids}
        for v in vids:
            name = v["name"]
            if " 2." in name:
                base = name.replace(" 2.", ".")
                orig = by_name.get(base)
                if orig and orig["size"] == v["size"] and orig["modifiedTime"] == v["modifiedTime"]:
                    continue
            out_path = RAW_DIR / cam / name
            jobs.append({
                "camera": cam,
                "kind": "video",
                "id": v["id"],
                "name": name,
                "size": int(v.get("size", 0)),
                "modifiedTime": v.get("modifiedTime", ""),
                "out": str(out_path),
            })

    # Also fetch the 3 stills directly from Drive folder listings
    for cam, fid in CAM_FOLDERS.items():
        items = ls_folder(fid)
        if len(items) == 1 and items[0].get("mimeType") == "application/vnd.google-apps.folder":
            items = ls_folder(items[0]["id"])
        for it in items:
            name = it["name"]
            if name.startswith("._"):
                continue
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".heic")):
                out_path = RAW_DIR / "STILLS" / f"{cam}_{name}"
                jobs.append({
                    "camera": cam,
                    "kind": "still",
                    "id": it["id"],
                    "name": name,
                    "size": int(it.get("size", 0)),
                    "modifiedTime": it.get("modifiedTime", ""),
                    "out": str(out_path),
                })

    # Download smaller files first for fast initial feedback, then larger files
    jobs.sort(key=lambda j: (j["camera"], j["size"]))
    return jobs


def download_one(job: dict) -> tuple[str, bool, str]:
    out_path = Path(job["out"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    expected = job["size"]
    if out_path.exists() and expected > 0 and out_path.stat().st_size == expected:
        return job["name"], True, "SKIP_EXISTS"

    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
    for attempt in range(1, 4):
        t0 = time.time()
        res = subprocess.run(
            ["gdrive", "readonly", "download", job["id"], "--out", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and tmp_path.exists():
            actual = tmp_path.stat().st_size
            if expected == 0 or actual == expected:
                tmp_path.rename(out_path)
                dt = time.time() - t0
                mb = actual / (1024 * 1024)
                return job["name"], True, f"OK {mb:.1f}MB in {dt:.1f}s"
            else:
                tmp_path.unlink(missing_ok=True)
        time.sleep(2 * attempt)
    return job["name"], False, f"FAILED: {res.stderr.strip()[:200]}"


def main() -> None:
    jobs = build_jobs()
    (ROOT / "data" / "download_jobs.json").write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")
    tot_gb = sum(j["size"] for j in jobs) / (1024 ** 3)
    print(f"Downloading {len(jobs)} unique files ({tot_gb:.2f} GB total) with 5 parallel workers...", flush=True)

    done = 0
    failed = []
    t_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(download_one, j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futs):
            job = futs[fut]
            name, ok, msg = fut.result()
            done += 1
            status = "OK" if ok else "ERR"
            print(f"[{done:02d}/{len(jobs)}] [{status}] {job['camera']}/{name}: {msg}", flush=True)
            if not ok:
                failed.append((job["camera"], name, msg))

    el = time.time() - t_start
    print(f"\nFinished in {el:.1f}s. Success: {len(jobs) - len(failed)}/{len(jobs)}.", flush=True)
    if failed:
        print("FAILED FILES:", failed, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
