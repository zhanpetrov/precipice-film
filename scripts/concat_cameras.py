#!/usr/bin/env python3
"""
Normalizes and concatenates all shots per camera into 3 master 1080p SDR BT.709
YouTube-ready MP4s (CHICARA_CAM, ROB_CAM, SECRET_CAM) using Apple Silicon
VideoToolbox hardware encoding, computes frame-accurate chapter timestamps,
and generates 1920x1080 hero thumbnails for each camera.
"""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
EXPORTS_DIR = ROOT / "exports"
NORM_DIR = EXPORTS_DIR / "_norm"
THUMBS_DIR = ROOT / "assets" / "thumbs"
DATA_DIR = ROOT / "data"

FFMPEG = "/Users/studio/.local/bin/ffmpeg"
FFPROBE = "/Users/studio/.local/bin/ffprobe"


def fmt_yt_ts(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
    ).strip()
    return float(out)


def normalize_shot(cam: str, shot: dict) -> tuple[str, Path, float]:
    src = RAW_DIR / cam / shot["filename"]
    out_dir = NORM_DIR / cam
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{shot['shot_index']:03d}_{shot['stem']}.mp4"

    if dst.exists() and dst.stat().st_size > 10_000:
        return shot["filename"], dst, probe_duration(dst)

    if shot.get("is_hdr"):
        vf = (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
            "zscale=t=linear:npl=203,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,fps=30"
        )
    else:
        vf = (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
            "format=yuv420p,fps=30"
        )

    cmd = [FFMPEG, "-y", "-i", str(src)]
    if shot.get("has_audio"):
        cmd += [
            "-vf", vf,
            "-c:v", "h264_videotoolbox", "-b:v", "6500k", "-maxrate", "9000k", "-bufsize", "12000k",
            "-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(dst), "-loglevel", "error",
        ]
    else:
        # Generate silent stereo audio track so concat demuxer has identical streams
        cmd += [
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-shortest",
            "-vf", vf,
            "-c:v", "h264_videotoolbox", "-b:v", "6500k", "-maxrate", "9000k", "-bufsize", "12000k",
            "-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(dst), "-loglevel", "error",
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Fallback without zscale if a clip has unusual HDR metadata
        vf_fb = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p,fps=30"
        cmd_fb = [
            FFMPEG, "-y", "-i", str(src),
            "-vf", vf_fb,
            "-c:v", "h264_videotoolbox", "-b:v", "6500k",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(dst), "-loglevel", "error",
        ]
        subprocess.run(cmd_fb, check=True)

    return shot["filename"], dst, probe_duration(dst)


def build_hero_thumb(cam: str, label: str, mp4_path: Path, dur: float) -> Path:
    out_jpg = THUMBS_DIR / f"HERO_{cam}.jpg"
    seek = min(max(dur * 0.12, 2.0), max(dur - 2.0, 0.0))
    subprocess.run(
        [
            FFMPEG, "-y", "-ss", f"{seek:.2f}", "-i", str(mp4_path),
            "-frames:v", "1", "-q:v", "2", str(out_jpg), "-loglevel", "error",
        ],
        check=True,
    )
    return out_jpg


def main() -> None:
    shots_data = json.loads((DATA_DIR / "shots.json").read_text(encoding="utf-8"))
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    concat_summary = {}

    for cam in ["CHICARA_CAM", "ROB_CAM", "SECRET_CAM"]:
        cam_info = shots_data["cameras"][cam]
        shots = cam_info["shots"]
        t0 = time.time()
        print(f"\n=== Normalizing {cam} ({len(shots)} shots) ===", flush=True)

        norm_results: dict[str, tuple[Path, float]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(normalize_shot, cam, s): s for s in shots}
            done = 0
            for fut in concurrent.futures.as_completed(futs):
                fname, dst, dur = fut.result()
                norm_results[fname] = (dst, dur)
                done += 1
                print(f"  [{done:02d}/{len(shots)}] {cam}/{fname} -> {dur:.2f}s", flush=True)

        # Build concat list in exact chronological order & compute exact offsets
        concat_txt = NORM_DIR / f"{cam}_concat.txt"
        lines = []
        cum = 0.0
        for s in shots:
            dst, dur = norm_results[s["filename"]]
            s["master_offset"] = round(cum, 3)
            s["master_duration"] = round(dur, 3)
            s["master_ts"] = fmt_yt_ts(cum)
            cum += dur
            safe_path = str(dst).replace("'", "'\\''")
            lines.append(f"file '{safe_path}'")

        concat_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

        master_mp4 = EXPORTS_DIR / f"PRECIPICE_{cam}_MASTER_1080p.mp4"
        if len(shots) == 1:
            only_path = norm_results[shots[0]["filename"]][0]
            subprocess.run(["cp", "-f", str(only_path), str(master_mp4)], check=True)
        else:
            subprocess.run(
                [
                    FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-c", "copy", "-movflags", "+faststart",
                    str(master_mp4), "-loglevel", "warning",
                ],
                check=True,
            )

        actual_dur = probe_duration(master_mp4)
        mb = master_mp4.stat().st_size / (1024 * 1024)
        hero = build_hero_thumb(cam, cam_info["label"], master_mp4, actual_dur)
        cam_info["master_duration"] = round(actual_dur, 3)
        cam_info["master_size_mb"] = round(mb, 1)
        cam_info["hero_thumb"] = f"assets/thumbs/{hero.name}"

        concat_summary[cam] = {
            "mp4": str(master_mp4),
            "duration_sec": round(actual_dur, 3),
            "duration_hms": fmt_yt_ts(actual_dur),
            "size_mb": round(mb, 1),
            "hero_thumb": str(hero),
            "shot_count": len(shots),
        }
        print(f"=== {cam} MASTER READY: {master_mp4.name} ({mb:.1f} MB, {fmt_yt_ts(actual_dur)}) in {time.time()-t0:.1f}s ===", flush=True)

    (DATA_DIR / "shots.json").write_text(json.dumps(shots_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (DATA_DIR / "concat_summary.json").write_text(json.dumps(concat_summary, indent=2) + "\n", encoding="utf-8")
    print("\nALL 3 CAMERA MASTERS BUILT!", flush=True)


if __name__ == "__main__":
    main()
