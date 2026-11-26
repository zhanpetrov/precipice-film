#!/usr/bin/env python3
"""
Probes, thumbnails, transcribes (MLX Whisper large-v3-turbo), and assembles
1080p SDR BT.709 YouTube masters + hero thumbnails for the 3 new Batch 2 cameras:
  - ZHAN_CAM      (Day 1 · Zhan Cam)
  - DAY2_ROB_CAM  (Day 2 · Rob Cam)
  - DAY2_ZHAN_CAM (Day 2 · Zhan Cam)
Merges them cleanly into existing data/shots.json without touching Day 1 cameras.
Run via: /Users/studio/.local/bin/uv run --with mlx-whisper python3 scripts/process_batch2.py
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import subprocess
import time
from pathlib import Path

import mlx_whisper

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw"
EXPORTS_DIR = ROOT / "exports"
NORM_DIR = EXPORTS_DIR / "_norm"
THUMBS_DIR = ROOT / "assets" / "thumbs"
STILLS_DIR = ROOT / "assets" / "stills"
TRANSCRIPTS_DIR = ROOT / "transcripts"
WAV_DIR = RAW_DIR / "_wav16k"
DATA_DIR = ROOT / "data"

FFMPEG = "/Users/studio/.local/bin/ffmpeg"
FFPROBE = "/Users/studio/.local/bin/ffprobe"

BATCH2_CAMERAS = [
    ("ZHAN_CAM", "Day 1 · Zhan Cam"),
    ("DAY2_ROB_CAM", "Day 2 · Rob Cam"),
    ("DAY2_ZHAN_CAM", "Day 2 · Zhan Cam"),
]


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def fmt_hms(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def fmt_srt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def probe_video(path: Path) -> dict:
    data = json.loads(subprocess.check_output(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        text=True,
    ))
    fmt = data.get("format", {})
    tags = fmt.get("tags", {})
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    astream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    w, h = int(vstream.get("width", 0)), int(vstream.get("height", 0))
    rot = 0
    for sd in vstream.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    disp_w, disp_h = (h, w) if abs(rot) in (90, 270) else (w, h)
    ct = (vstream.get("color_transfer") or "").lower()
    fps_str = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate") or "30/1"
    try:
        num, den = fps_str.split("/")
        fps = round(float(num) / float(den), 3) if float(den) else 30.0
    except Exception:
        fps = 30.0
    return {
        "duration": float(fmt.get("duration") or vstream.get("duration") or 0.0),
        "size_bytes": path.stat().st_size,
        "width": w,
        "height": h,
        "display_width": disp_w,
        "display_height": disp_h,
        "rotation": rot,
        "is_portrait": disp_h > disp_w,
        "fps": fps,
        "codec": vstream.get("codec_name", ""),
        "color_transfer": ct,
        "is_hdr": ct in ("arib-std-b67", "smpte2084"),
        "has_audio": astream is not None,
        "audio_channels": int(astream.get("channels", 0)) if astream else 0,
        "creation_time": tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time") or "",
    }


def probe_duration(path: Path) -> float:
    return float(subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
    ).strip())


def extract_wav_and_thumb(cam: str, path: Path, meta: dict) -> None:
    stem = path.stem
    wav_path = WAV_DIR / cam / f"{stem}.wav"
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path = THUMBS_DIR / cam / f"{stem}.jpg"
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    if meta["has_audio"] and not wav_path.exists():
        subprocess.run(
            [FFMPEG, "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path), "-loglevel", "error"],
            check=True,
        )
    if not thumb_path.exists():
        seek = min(max(meta["duration"] * 0.15, 0.5), max(meta["duration"] - 0.5, 0.0))
        vf = (
            "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black,"
            "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuvj420p"
            if meta["is_hdr"]
            else "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black,format=yuvj420p"
        )
        res = subprocess.run([FFMPEG, "-y", "-ss", f"{seek:.2f}", "-i", str(path), "-frames:v", "1", "-vf", vf, "-q:v", "3", str(thumb_path), "-loglevel", "error"], capture_output=True)
        if res.returncode != 0 or not thumb_path.exists():
            subprocess.run([FFMPEG, "-y", "-ss", f"{seek:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black", "-q:v", "3", str(thumb_path), "-loglevel", "error"], check=False)


def normalize_shot(cam: str, shot: dict, src: Path) -> tuple[str, Path, float]:
    out_dir = NORM_DIR / cam
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{shot['shot_index']:03d}_{shot['stem']}.mp4"
    if dst.exists() and dst.stat().st_size > 10_000:
        return shot["filename"], dst, probe_duration(dst)

    vf = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
        "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,fps=30"
        if shot.get("is_hdr")
        else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p,fps=30"
    )
    cmd = [FFMPEG, "-y", "-i", str(src)]
    if not shot.get("has_audio"):
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-shortest"]
    cmd += [
        "-vf", vf, "-c:v", "h264_videotoolbox", "-b:v", "6500k", "-maxrate", "9000k", "-bufsize", "12000k",
        "-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        str(dst), "-loglevel", "error",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        vf_fb = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p,fps=30"
        subprocess.run([FFMPEG, "-y", "-i", str(src), "-vf", vf_fb, "-c:v", "h264_videotoolbox", "-b:v", "6500k", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(dst), "-loglevel", "error"], check=True)
    return shot["filename"], dst, probe_duration(dst)


def main() -> None:
    t0 = time.time()
    shots_data = json.loads((DATA_DIR / "shots.json").read_text(encoding="utf-8"))

    # Convert any new stills in raw/STILLS/
    existing_stills = {s["filename"] for s in shots_data.get("stills", [])}
    for p in sorted((RAW_DIR / "STILLS").iterdir()):
        if p.is_file() and not p.name.startswith(".") and p.name not in existing_stills:
            dst = STILLS_DIR / f"{p.stem}.jpg"
            if not dst.exists():
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", "1600", str(p), "--out", str(dst)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if dst.exists():
                shots_data.setdefault("stills", []).append({"filename": p.name, "path": f"assets/stills/{dst.name}"})

    for cam, label in BATCH2_CAMERAS:
        cam_dir = RAW_DIR / cam
        if not cam_dir.exists():
            continue
        files = [p for p in cam_dir.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".mov", ".mp4", ".m4v")]
        if not files:
            print(f"[{cam}] No video files — skipping.", flush=True)
            continue

        print(f"\n=== [{cam}] Probing {len(files)} shots ===", flush=True)
        entries = []
        for p in files:
            meta = probe_video(p)
            entries.append({"camera": cam, "filename": p.name, "stem": p.stem, "path": str(p), **meta})
        entries.sort(key=lambda x: (x["creation_time"] or "9999", natural_key(x["filename"])))
        for idx, e in enumerate(entries, 1):
            e["shot_index"] = idx

        # Extract WAVs + thumbs in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lambda e: extract_wav_and_thumb(cam, Path(e["path"]), e), entries))

        # Transcribe with MLX Whisper
        print(f"=== [{cam}] Transcribing {len(entries)} shots with MLX Whisper ===", flush=True)
        out_tr_dir = TRANSCRIPTS_DIR / cam
        out_tr_dir.mkdir(parents=True, exist_ok=True)
        for e in entries:
            stem = e["stem"]
            jpath = out_tr_dir / f"{stem}.json"
            wpath = WAV_DIR / cam / f"{stem}.wav"
            if jpath.exists():
                cached = json.loads(jpath.read_text(encoding="utf-8"))
                segs, full_txt, lang = cached.get("segments", []), cached.get("text", ""), cached.get("language", "en")
            elif not e["has_audio"] or not wpath.exists():
                segs, full_txt, lang = [], "", "en"
            else:
                res = mlx_whisper.transcribe(str(wpath), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", word_timestamps=False, verbose=False, condition_on_previous_text=True)
                lang = res.get("language", "en")
                segs = []
                for s in res.get("segments", []):
                    tx = s["text"].strip()
                    if tx:
                        segs.append({"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": tx})
                full_txt = " ".join(s["text"] for s in segs).strip()
                jpath.write_text(json.dumps({"camera": cam, "shot": stem, "duration": e["duration"], "creation_time": e["creation_time"], "language": lang, "text": full_txt, "segments": segs}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                (out_tr_dir / f"{stem}.txt").write_text("\n".join(f"[{fmt_hms(s['start'])} -> {fmt_hms(s['end'])}] {s['text']}" for s in segs) + ("\n" if segs else ""), encoding="utf-8")
                (out_tr_dir / f"{stem}.srt").write_text("\n".join(f"{k}\n{fmt_srt_ts(s['start'])} --> {fmt_srt_ts(s['end'])}\n{s['text']}\n" for k, s in enumerate(segs, 1)), encoding="utf-8")

            e["language"] = lang
            e["text"] = full_txt
            e["word_count"] = len(full_txt.split()) if full_txt else 0
            e["segments"] = segs
            e["thumb"] = f"assets/thumbs/{cam}/{stem}.jpg"
            e["transcript_txt"] = f"transcripts/{cam}/{stem}.txt"
            e["transcript_srt"] = f"transcripts/{cam}/{stem}.srt"
            e["transcript_json"] = f"transcripts/{cam}/{stem}.json"
            print(f"  [{e['shot_index']:02d}/{len(entries)}] {cam}/{e['filename']} ({fmt_hms(e['duration'])}) -> {e['word_count']}w", flush=True)

        # Normalize & concatenate to 1080p SDR BT.709 YouTube master
        print(f"=== [{cam}] Assembling 1080p YouTube master ({len(entries)} shots) ===", flush=True)
        norm_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(normalize_shot, cam, e, Path(e["path"])): e for e in entries}
            for fut in concurrent.futures.as_completed(futs):
                fn, dst, dur = fut.result()
                norm_results[fn] = (dst, dur)

        concat_lines = []
        cam_full_txt = []
        cam_full_srt = []
        srt_counter = 1
        cum = 0.0
        for e in entries:
            dst, dur = norm_results[e["filename"]]
            e["camera_offset"] = round(cum, 3)
            e["master_offset"] = round(cum, 3)
            e["master_duration"] = round(dur, 3)
            e["master_ts"] = fmt_hms(cum)
            safe_p = str(dst).replace("'", "'\\''")
            concat_lines.append(f"file '{safe_p}'")

            cam_full_txt.append(f"\n=== SHOT {e['shot_index']:02d}: {e['filename']} @ {fmt_hms(cum)} ({fmt_hms(dur)}) ===")
            for seg in e["segments"]:
                gs, ge = cum + seg["start"], cum + seg["end"]
                cam_full_txt.append(f"[{fmt_hms(gs)}] {seg['text']}")
                cam_full_srt.append(f"{srt_counter}\n{fmt_srt_ts(gs)} --> {fmt_srt_ts(ge)}\n{seg['text']}\n")
                srt_counter += 1
            cum += dur

        (TRANSCRIPTS_DIR / f"{cam}_FULL.txt").write_text("\n".join(cam_full_txt).strip() + "\n", encoding="utf-8")
        (TRANSCRIPTS_DIR / f"{cam}_FULL.srt").write_text("\n".join(cam_full_srt), encoding="utf-8")

        concat_txt = NORM_DIR / f"{cam}_concat.txt"
        concat_txt.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        master_mp4 = EXPORTS_DIR / f"PRECIPICE_{cam}_MASTER_1080p.mp4"
        if len(entries) == 1:
            subprocess.run(["cp", "-f", str(norm_results[entries[0]["filename"]][0]), str(master_mp4)], check=True)
        else:
            subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", "-movflags", "+faststart", str(master_mp4), "-loglevel", "error"], check=True)

        actual_dur = probe_duration(master_mp4)
        mb = master_mp4.stat().st_size / (1024 * 1024)
        hero_jpg = THUMBS_DIR / f"HERO_{cam}.jpg"
        seek = min(max(actual_dur * 0.12, 2.0), max(actual_dur - 2.0, 0.0))
        subprocess.run([FFMPEG, "-y", "-ss", f"{seek:.2f}", "-i", str(master_mp4), "-frames:v", "1", "-q:v", "2", str(hero_jpg), "-loglevel", "error"], check=True)

        public_shots = [{k: v for k, v in e.items() if k != "path"} for e in entries]
        shots_data["cameras"][cam] = {
            "id": cam,
            "label": label,
            "shot_count": len(public_shots),
            "total_duration": round(sum(x["duration"] for x in public_shots), 3),
            "master_duration": round(actual_dur, 3),
            "master_size_mb": round(mb, 1),
            "hero_thumb": f"assets/thumbs/{hero_jpg.name}",
            "total_words": sum(x["word_count"] for x in public_shots),
            "full_transcript_txt": f"transcripts/{cam}_FULL.txt",
            "full_transcript_srt": f"transcripts/{cam}_FULL.srt",
            "shots": public_shots,
        }
        (DATA_DIR / "shots.json").write_text(json.dumps(shots_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"=== [{cam}] MASTER READY: {master_mp4.name} ({mb:.1f} MB, {fmt_hms(actual_dur)}) ===", flush=True)

    print(f"\nALL BATCH 2 CAMERAS TRANSCRIBED & ASSEMBLED in {time.time()-t0:.1f}s!", flush=True)


if __name__ == "__main__":
    main()
