#!/usr/bin/env python3
"""
Lists and downloads all new PRECIPICE Batch 2 camera footage from Google Drive:
  - ZHAN_CAM      (Day 1 · Zhan Cam)
  - DAY2_ROB_CAM  (Day 2 · Rob Cam)
  - DAY2_ZHAN_CAM (Day 2 · Zhan Cam)
Uses exponential backoff on Drive rate limits and resumes cleanly by byte size.
"""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
DATA_DIR = ROOT / "data"

CAMS = [
    ("ZHAN_CAM", "Day 1 · Zhan Cam", "1a3vzic8hSVGA7K93sed3aB1h_sTtEEYS"),
    ("DAY2_ROB_CAM", "Day 2 · Rob Cam", "1QlrMr2l8kx0W3C-i1PVHW1Y8axkPeY_l"),
    ("DAY2_ZHAN_CAM", "Day 2 · Zhan Cam", "1RwSF_EmYRKCvR51JH9clUt9w3VcjXWpo"),
]


def ls_folder_retry(fid: str) -> list[dict]:
    for attempt in range(1, 10):
        res = subprocess.run(["gdrive", "readonly", "ls", fid, "--max", "0", "--json"], capture_output=True, text=True)
        if res.returncode == 0:
            return json.loads(res.stdout)
        wait = min(30, 6 * attempt)
        print(f"  [ls retry {attempt}] waiting {wait}s...", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"Failed to list {fid}: {res.stderr}")


def download_one(job: dict) -> tuple[str, bool, str]:
    out_path = Path(job["out"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    expected = job["size"]
    if out_path.exists() and expected > 0 and out_path.stat().st_size == expected:
        return job["name"], True, "SKIP_EXISTS"

    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
    for attempt in range(1, 8):
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
                return job["name"], True, f"OK {actual/(1024*1024):.1f}MB in {dt:.1f}s"
            tmp_path.unlink(missing_ok=True)
        wait = min(30, 5 * attempt)
        time.sleep(wait)
    return job["name"], False, f"FAILED: {res.stderr.strip()[:160]}"


def main() -> None:
    manifest = {}
    jobs = []

    for cid, label, fid in CAMS:
        items = [x for x in ls_folder_retry(fid) if not x["name"].startswith("._")]
        # Unwrap single nested folder if present
        if len(items) == 1 and items[0].get("mimeType") == "application/vnd.google-apps.folder":
            items = [x for x in ls_folder_retry(items[0]["id"]) if not x["name"].startswith("._")]

        vids = [x for x in items if x["name"].lower().endswith((".mov", ".mp4", ".m4v"))]
        stills = [x for x in items if x["name"].lower().endswith((".jpg", ".jpeg", ".png", ".heic"))]

        by_name = {v["name"]: v for v in vids}
        unique_vids = []
        for v in sorted(vids, key=lambda a: a["name"]):
            if " 2." in v["name"]:
                base = v["name"].replace(" 2.", ".")
                orig = by_name.get(base)
                if orig and orig.get("size") == v.get("size") and orig.get("modifiedTime") == v.get("modifiedTime"):
                    continue
            unique_vids.append(v)

        gb = sum(int(x.get("size", 0)) for x in unique_vids) / (1024 ** 3)
        manifest[cid] = {
            "id": cid,
            "label": label,
            "folder_id": fid,
            "video_count": len(unique_vids),
            "still_count": len(stills),
            "total_gb": round(gb, 2),
            "videos": unique_vids,
            "stills": stills,
        }
        print(f"{cid:15s} ({label:18s}): {len(unique_vids):2d} videos ({gb:.2f} GB), {len(stills)} stills", flush=True)

        for v in unique_vids:
            jobs.append({
                "camera": cid,
                "kind": "video",
                "id": v["id"],
                "name": v["name"],
                "size": int(v.get("size", 0)),
                "out": str(RAW_DIR / cid / v["name"]),
            })
        for st in stills:
            jobs.append({
                "camera": cid,
                "kind": "still",
                "id": st["id"],
                "name": st["name"],
                "size": int(st.get("size", 0)),
                "out": str(RAW_DIR / "STILLS" / f"{cid}_{st['name']}"),
            })

    (DATA_DIR / "drive_batch2_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tot_gb = sum(j["size"] for j in jobs) / (1024 ** 3)
    print(f"\nDownloading {len(jobs)} new files ({tot_gb:.2f} GB total) with 3 parallel workers...", flush=True)

    jobs.sort(key=lambda j: (j["camera"], j["size"]))
    done = 0
    failed = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(download_one, j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futs):
            j = futs[fut]
            name, ok, msg = fut.result()
            done += 1
            print(f"[{done:02d}/{len(jobs)}] [{'OK' if ok else 'ERR'}] {j['camera']}/{name}: {msg}", flush=True)
            if not ok:
                failed.append((j["camera"], name, msg))

    print(f"\nBatch 2 download finished in {time.time()-t0:.1f}s: {len(jobs)-len(failed)}/{len(jobs)} OK.", flush=True)
    if failed:
        print("FAILED:", failed, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
