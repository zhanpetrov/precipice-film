#!/usr/bin/env python3
"""
Probes all downloaded PRECIPICE camera shots, extracts tone-mapped thumbnails and
16kHz mono WAVs, transcribes every shot with MLX Whisper (whisper-large-v3-turbo),
and writes per-shot JSON/SRT/TXT transcripts plus data/shots.json.
Run via: /Users/studio/.local/bin/uv run --with mlx-whisper python3 scripts/probe_and_transcribe.py
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
TRANSCRIPTS_DIR = ROOT / "transcripts"
THUMBS_DIR = ROOT / "assets" / "thumbs"
STILLS_DIR = ROOT / "assets" / "stills"
WAV_DIR = RAW_DIR / "_wav16k"
DATA_DIR = ROOT / "data"

FFMPEG = "/Users/studio/.local/bin/ffmpeg"
FFPROBE = "/Users/studio/.local/bin/ffprobe"

CAMERAS = [
    ("CHICARA_CAM", "Chicara Cam"),
    ("ROB_CAM", "Rob Cam"),
    ("SECRET_CAM", "Secret Cam"),
]


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


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


def fmt_hms(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def probe_video(path: Path) -> dict:
    cmd = [
        FFPROBE, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    data = json.loads(subprocess.check_output(cmd, text=True))
    fmt = data.get("format", {})
    tags = fmt.get("tags", {})
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    astream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    w = int(vstream.get("width", 0))
    h = int(vstream.get("height", 0))
    rotation = 0
    for sd in vstream.get("side_data_list", []):
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    if abs(rotation) in (90, 270):
        disp_w, disp_h = h, w
    else:
        disp_w, disp_h = w, h

    ct = (vstream.get("color_transfer") or "").lower()
    is_hdr = ct in ("arib-std-b67", "smpte2084")

    fps_str = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate") or "30/1"
    try:
        num, den = fps_str.split("/")
        fps = round(float(num) / float(den), 3) if float(den) else 30.0
    except Exception:
        fps = 30.0

    creation = (
        tags.get("com.apple.quicktime.creationdate")
        or tags.get("creation_time")
        or ""
    )

    return {
        "duration": float(fmt.get("duration") or vstream.get("duration") or 0.0),
        "size_bytes": path.stat().st_size,
        "width": w,
        "height": h,
        "display_width": disp_w,
        "display_height": disp_h,
        "rotation": rotation,
        "is_portrait": disp_h > disp_w,
        "fps": fps,
        "codec": vstream.get("codec_name", ""),
        "color_transfer": ct,
        "is_hdr": is_hdr,
        "has_audio": astream is not None,
        "audio_channels": int(astream.get("channels", 0)) if astream else 0,
        "creation_time": creation,
    }


def extract_wav_and_thumb(cam: str, path: Path, meta: dict) -> tuple[Path, Path]:
    stem = path.stem
    wav_path = WAV_DIR / cam / f"{stem}.wav"
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path = THUMBS_DIR / cam / f"{stem}.jpg"
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Extract 16kHz mono WAV if audio exists
    if meta["has_audio"] and not wav_path.exists():
        subprocess.run(
            [
                FFMPEG, "-y", "-i", str(path),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(wav_path), "-loglevel", "error",
            ],
            check=True,
        )

    # 2. Extract 640x360 SDR thumbnail
    if not thumb_path.exists():
        seek = min(max(meta["duration"] * 0.15, 0.5), max(meta["duration"] - 0.5, 0.0))
        if meta["is_hdr"]:
            vf = (
                "scale=640:360:force_original_aspect_ratio=decrease,"
                "pad=640:360:(ow-iw)/2:(oh-ih)/2:black,"
                "zscale=t=linear:npl=203,format=gbrpf32le,"
                "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:r=tv,format=yuvj420p"
            )
        else:
            vf = (
                "scale=640:360:force_original_aspect_ratio=decrease,"
                "pad=640:360:(ow-iw)/2:(oh-ih)/2:black,format=yuvj420p"
            )
        res = subprocess.run(
            [
                FFMPEG, "-y", "-ss", f"{seek:.2f}", "-i", str(path),
                "-frames:v", "1", "-vf", vf, "-q:v", "3",
                str(thumb_path), "-loglevel", "error",
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0 or not thumb_path.exists():
            # Fallback without zscale
            subprocess.run(
                [
                    FFMPEG, "-y", "-ss", f"{seek:.2f}", "-i", str(path),
                    "-frames:v", "1",
                    "-vf", "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black",
                    "-q:v", "3", str(thumb_path), "-loglevel", "error",
                ],
                check=False,
            )

    return wav_path, thumb_path


def convert_stills() -> list[dict]:
    STILLS_DIR.mkdir(parents=True, exist_ok=True)
    stills_raw = RAW_DIR / "STILLS"
    out = []
    if not stills_raw.exists():
        return out
    for p in sorted(stills_raw.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        dst = STILLS_DIR / f"{p.stem}.jpg"
        if not dst.exists():
            if p.suffix.lower() == ".heic":
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", "1600", str(p), "--out", str(dst)], check=False)
            else:
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", "1600", str(p), "--out", str(dst)], check=False)
        if dst.exists():
            out.append({
                "filename": p.name,
                "path": f"assets/stills/{dst.name}",
            })
    return out


def write_shot_transcripts(cam: str, stem: str, res: dict, meta: dict) -> dict:
    out_dir = TRANSCRIPTS_DIR / cam
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = []
    srt_lines = []
    txt_lines = []
    full_text_parts = []

    for idx, seg in enumerate(res.get("segments", []), 1):
        s = round(float(seg["start"]), 2)
        e = round(float(seg["end"]), 2)
        t = seg["text"].strip()
        if not t:
            continue
        segments.append({"start": s, "end": e, "text": t})
        srt_lines.append(f"{idx}\n{fmt_srt_ts(s)} --> {fmt_srt_ts(e)}\n{t}\n")
        txt_lines.append(f"[{fmt_hms(s)} -> {fmt_hms(e)}] {t}")
        full_text_parts.append(t)

    full_text = " ".join(full_text_parts).strip()

    json_payload = {
        "camera": cam,
        "shot": stem,
        "duration": meta["duration"],
        "creation_time": meta["creation_time"],
        "language": res.get("language", "en"),
        "text": full_text,
        "segments": segments,
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(json_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / f"{stem}.srt").write_text("\n".join(srt_lines), encoding="utf-8")
    (out_dir / f"{stem}.txt").write_text("\n".join(txt_lines) + ("\n" if txt_lines else ""), encoding="utf-8")

    return {
        "language": res.get("language", "en"),
        "text": full_text,
        "word_count": len(full_text.split()) if full_text else 0,
        "segment_count": len(segments),
        "segments": segments,
    }


def main() -> None:
    t0 = time.time()
    print("=== Step 1: Converting production stills ===", flush=True)
    stills = convert_stills()
    print(f"Converted {len(stills)} stills.", flush=True)

    print("=== Step 2: Probing all downloaded shots ===", flush=True)
    camera_shots: dict[str, list[dict]] = {}
    for cam, label in CAMERAS:
        cam_dir = RAW_DIR / cam
        files = [
            p for p in cam_dir.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".mov", ".mp4", ".m4v")
        ]
        entries = []
        for p in files:
            meta = probe_video(p)
            entries.append({"camera": cam, "filename": p.name, "stem": p.stem, "path": str(p), **meta})
        # Sort chronologically by creation_time, tie-break by natural filename
        entries.sort(key=lambda x: (x["creation_time"] or "9999", natural_key(x["filename"])))
        camera_shots[cam] = entries
        tot_min = sum(x["duration"] for x in entries) / 60.0
        print(f"  {cam}: {len(entries)} shots, total {tot_min:.1f} min", flush=True)

    print("=== Step 3: Extracting WAVs + tone-mapped thumbnails in parallel ===", flush=True)
    all_items = [(cam, e) for cam, entries in camera_shots.items() for e in entries]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(extract_wav_and_thumb, cam, Path(e["path"]), e) for cam, e in all_items]
        for fut in concurrent.futures.as_completed(futs):
            fut.result()
    print(f"Extracted WAVs & thumbnails for {len(all_items)} shots in {time.time()-t0:.1f}s.", flush=True)

    print("=== Step 4: Transcribing all shots with MLX Whisper (whisper-large-v3-turbo) ===", flush=True)
    t_w = time.time()
    done = 0
    for cam, entries in camera_shots.items():
        cum_offset = 0.0
        cam_full_txt = []
        cam_full_srt = []
        srt_counter = 1

        for idx, e in enumerate(entries, 1):
            done += 1
            stem = e["stem"]
            json_path = TRANSCRIPTS_DIR / cam / f"{stem}.json"
            wav_path = WAV_DIR / cam / f"{stem}.wav"

            if json_path.exists():
                cached = json.loads(json_path.read_text(encoding="utf-8"))
                tr = {
                    "language": cached.get("language", "en"),
                    "text": cached.get("text", ""),
                    "word_count": len(cached.get("text", "").split()),
                    "segment_count": len(cached.get("segments", [])),
                    "segments": cached.get("segments", []),
                }
                status = "CACHED"
            elif not e["has_audio"] or not wav_path.exists():
                tr = write_shot_transcripts(cam, stem, {"language": "en", "segments": []}, e)
                status = "NO_AUDIO"
            else:
                ts0 = time.time()
                res = mlx_whisper.transcribe(
                    str(wav_path),
                    path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
                    word_timestamps=False,
                    verbose=False,
                    condition_on_previous_text=True,
                )
                tr = write_shot_transcripts(cam, stem, res, e)
                status = f"{time.time()-ts0:.1f}s ({tr['word_count']}w)"

            e["shot_index"] = idx
            e["camera_offset"] = round(cum_offset, 3)
            e["thumb"] = f"assets/thumbs/{cam}/{stem}.jpg"
            e["transcript_txt"] = f"transcripts/{cam}/{stem}.txt"
            e["transcript_srt"] = f"transcripts/{cam}/{stem}.srt"
            e["transcript_json"] = f"transcripts/{cam}/{stem}.json"
            e["language"] = tr["language"]
            e["word_count"] = tr["word_count"]
            e["text"] = tr["text"]
            e["segments"] = tr["segments"]

            # Append to combined camera transcript
            cam_full_txt.append(f"\n=== SHOT {idx:02d}: {e['filename']} @ {fmt_hms(cum_offset)} ({fmt_hms(e['duration'])}) ===")
            for seg in tr["segments"]:
                g_s = cum_offset + seg["start"]
                g_e = cum_offset + seg["end"]
                cam_full_txt.append(f"[{fmt_hms(g_s)}] {seg['text']}")
                cam_full_srt.append(f"{srt_counter}\n{fmt_srt_ts(g_s)} --> {fmt_srt_ts(g_e)}\n{seg['text']}\n")
                srt_counter += 1

            cum_offset += e["duration"]
            print(f"  [{done:02d}/{len(all_items)}] {cam}/{e['filename']} ({fmt_hms(e['duration'])}) -> {status}", flush=True)

        (TRANSCRIPTS_DIR / f"{cam}_FULL.txt").write_text("\n".join(cam_full_txt).strip() + "\n", encoding="utf-8")
        (TRANSCRIPTS_DIR / f"{cam}_FULL.srt").write_text("\n".join(cam_full_srt), encoding="utf-8")

    # Strip local raw path before committing to GitHub JSON
    public_data = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stills": stills,
        "cameras": {},
    }
    for cam, label in CAMERAS:
        entries = camera_shots[cam]
        public_shots = []
        for e in entries:
            pe = {k: v for k, v in e.items() if k != "path"}
            public_shots.append(pe)
        public_data["cameras"][cam] = {
            "id": cam,
            "label": label,
            "shot_count": len(public_shots),
            "total_duration": round(sum(x["duration"] for x in public_shots), 3),
            "total_words": sum(x["word_count"] for x in public_shots),
            "full_transcript_txt": f"transcripts/{cam}_FULL.txt",
            "full_transcript_srt": f"transcripts/{cam}_FULL.srt",
            "shots": public_shots,
        }

    (DATA_DIR / "shots.json").write_text(json.dumps(public_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nALL TRANSCRIPTION COMPLETE in {time.time()-t_w:.1f}s! Wrote data/shots.json", flush=True)


if __name__ == "__main__":
    main()
