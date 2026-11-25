#!/usr/bin/env python3
"""
Processes Chikara Motomura's Nov 23, 2026 Hightail package (Rob's Precipice 112326):
  1. Converts 339 HEIC Cast Stills -> web thumbnails (480px) + lightbox JPGs (1280px)
  2. Encodes 44 Cast 1-Min Voice References + 3 Scene Audio Recordings -> web MP3s
  3. Transcribes all 44 voice refs, 3 scene audio recordings, and 5 MOV videos with MLX Whisper
  4. Assembles the 5 MOV videos into a 1080p SDR BT.709 YouTube master + hero thumbnail
  5. Updates data/shots.json, data/chapters.json, and writes data/hightail_112326.json
Run via: /Users/studio/.local/bin/uv run --with mlx-whisper python3 scripts/process_hightail_112326.py
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
SRC_ROOT = ROOT / "raw" / "hightail_112326" / "extracted" / "Rob's Precipice 112326"
DATA_DIR = ROOT / "data"
EXPORTS_DIR = ROOT / "exports"
THUMBS_DIR = ROOT / "assets" / "thumbs"
STILLS_THUMB_DIR = ROOT / "assets" / "cast_stills" / "thumbs"
STILLS_FULL_DIR = ROOT / "assets" / "cast_stills" / "full"
VOICE_MP3_DIR = ROOT / "assets" / "audio" / "voice_refs"
SCENE_MP3_DIR = ROOT / "assets" / "audio" / "scene_audio"
TRANSCRIPTS_DIR = ROOT / "transcripts"
WAV_TMP_DIR = ROOT / "raw" / "_wav16k" / "CHIKARA_BONUS"

FFMPEG = "/Users/studio/.local/bin/ffmpeg"
FFPROBE = "/Users/studio/.local/bin/ffprobe"


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def clean_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_")


def fmt_hms(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


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


def probe_media(path: Path) -> dict:
    data = json.loads(subprocess.check_output(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        text=True,
    ))
    fmt = data.get("format", {})
    tags = fmt.get("tags", {})
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    astream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    out = {
        "duration": float(fmt.get("duration") or (vstream or astream or {}).get("duration") or 0.0),
        "size_bytes": path.stat().st_size,
        "has_audio": astream is not None,
        "creation_time": tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time") or "",
    }
    if vstream:
        w, h = int(vstream.get("width", 0)), int(vstream.get("height", 0))
        rot = 0
        for sd in vstream.get("side_data_list", []):
            if "rotation" in sd:
                rot = int(sd["rotation"])
        disp_w, disp_h = (h, w) if abs(rot) in (90, 270) else (w, h)
        ct = (vstream.get("color_transfer") or "").lower()
        out.update({
            "width": w, "height": h,
            "display_width": disp_w, "display_height": disp_h,
            "rotation": rot, "is_portrait": disp_h > disp_w,
            "color_transfer": ct, "is_hdr": ct in ("arib-std-b67", "smpte2084"),
        })
    return out


def convert_one_still(src: Path) -> dict | None:
    stem = clean_stem(src.name)
    thumb = STILLS_THUMB_DIR / f"{stem}.jpg"
    full = STILLS_FULL_DIR / f"{stem}.jpg"
    if not thumb.exists():
        subprocess.run(
            ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "72", "-Z", "480", str(src), "--out", str(thumb)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    if not full.exists():
        subprocess.run(
            ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "78", "-Z", "1280", str(src), "--out", str(full)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    if thumb.exists() and full.exists():
        return {
            "id": stem,
            "filename": src.name,
            "thumb": f"assets/cast_stills/thumbs/{thumb.name}",
            "full": f"assets/cast_stills/full/{full.name}",
        }
    return None


def encode_audio_m4a(src: Path, dst: Path, stereo_pair: Path | None = None) -> float:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        if stereo_pair and stereo_pair.exists():
            # Merge Tr1 + Tr2 into a balanced stereo M4A
            subprocess.run(
                [
                    FFMPEG, "-y", "-i", str(src), "-i", str(stereo_pair),
                    "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]",
                    "-map", "[a]", "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(dst), "-loglevel", "error",
                ],
                check=True,
            )
        else:
            subprocess.run(
                [
                    FFMPEG, "-y", "-i", str(src),
                    "-ac", "1", "-ar", "44100", "-c:a", "aac", "-b:a", "96k",
                    "-movflags", "+faststart", str(dst), "-loglevel", "error",
                ],
                check=True,
            )
    return probe_media(dst)["duration"]


def transcribe_file(audio_path: Path) -> tuple[str, list[dict]]:
    res = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
        word_timestamps=False,
        verbose=False,
        condition_on_previous_text=True,
    )
    segs = []
    parts = []
    for seg in res.get("segments", []):
        t = seg["text"].strip()
        if not t:
            continue
        segs.append({"start": round(float(seg["start"]), 2), "end": round(float(seg["end"]), 2), "text": t})
        parts.append(t)
    return " ".join(parts).strip(), segs


def main() -> None:
    t0 = time.time()
    STILLS_THUMB_DIR.mkdir(parents=True, exist_ok=True)
    STILLS_FULL_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_MP3_DIR.mkdir(parents=True, exist_ok=True)
    SCENE_MP3_DIR.mkdir(parents=True, exist_ok=True)
    WAV_TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TRANSCRIPTS_DIR / "CHIKARA_BONUS").mkdir(parents=True, exist_ok=True)
    (THUMBS_DIR / "CHIKARA_BONUS").mkdir(parents=True, exist_ok=True)

    # 1. Convert 339 Cast Stills in parallel
    stills_src_dir = SRC_ROOT / "Cast Stills"
    still_files = sorted(
        [p for p in stills_src_dir.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".heic", ".jpg", ".jpeg", ".png")],
        key=lambda p: natural_key(p.name),
    )
    print(f"=== [1/5] Converting {len(still_files)} Cast Stills (8 parallel workers) ===", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        cast_stills = [r for r in ex.map(convert_one_still, still_files) if r]
    print(f"  Converted {len(cast_stills)} cast stills in {time.time()-t0:.1f}s", flush=True)

    # 2. Encode 44 Voice References + 3 Scene Audio Recordings -> M4A
    t1 = time.time()
    voice_dir = SRC_ROOT / "Cast I min voice reference"
    voice_wavs = sorted(
        [p for p in voice_dir.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".wav"],
        key=lambda p: natural_key(p.name),
    )
    print(f"=== [2/5] Encoding {len(voice_wavs)} Voice Refs + Scene Audio to M4A ===", flush=True)
    voice_items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = []
        for p in voice_wavs:
            stem = clean_stem(p.name)
            dst = VOICE_MP3_DIR / f"{stem}.m4a"
            futs.append((p, stem, dst, ex.submit(encode_audio_m4a, p, dst, None)))
        for p, stem, dst, fut in futs:
            dur = fut.result()
            voice_items.append({
                "id": stem,
                "filename": p.name,
                "audio": f"assets/audio/voice_refs/{dst.name}",
                "duration": round(dur, 2),
                "duration_hms": fmt_hms(dur),
                "src": str(p),
            })

    scene_dir = SRC_ROOT / "Scene audio recording"
    scene_groups: dict[str, dict[str, Path]] = {}
    for p in sorted(scene_dir.iterdir(), key=lambda x: natural_key(x.name)):
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".wav":
            base = re.sub(r"_Tr\d+$", "", p.stem)
            tr = "tr2" if p.stem.endswith("_Tr2") else "tr1"
            scene_groups.setdefault(base, {})[tr] = p

    scene_items = []
    for base, grp in sorted(scene_groups.items(), key=lambda kv: natural_key(kv[0])):
        tr1 = grp.get("tr1") or grp.get("tr2")
        tr2 = grp.get("tr2") if "tr1" in grp else None
        dst = SCENE_MP3_DIR / f"{base}_MIX.m4a"
        dur = encode_audio_m4a(tr1, dst, tr2)
        scene_items.append({
            "id": base,
            "filename": f"{base} (Tr1 + Tr2 Mix)" if tr2 else tr1.name,
            "audio": f"assets/audio/scene_audio/{dst.name}",
            "duration": round(dur, 2),
            "duration_hms": fmt_hms(dur),
            "src": str(dst),
        })
    print(f"  Encoded {len(voice_items)} voice refs + {len(scene_items)} scene audio mixes in {time.time()-t1:.1f}s", flush=True)

    # 3. Transcribe all 44 voice refs + 3 scene audio mixes
    t2 = time.time()
    print(f"=== [3/5] Transcribing {len(voice_items)} Voice Refs + {len(scene_items)} Scene Audio ===", flush=True)
    for i, v in enumerate(voice_items, 1):
        txt, segs = transcribe_file(Path(v["src"]))
        v["text"] = txt
        v["word_count"] = len(txt.split()) if txt else 0
        v["segments"] = segs
        del v["src"]
        if i % 10 == 0 or i == len(voice_items):
            print(f"  Voice refs [{i}/{len(voice_items)}] done ({v['id']}: {v['word_count']}w)", flush=True)

    for s in scene_items:
        txt, segs = transcribe_file(Path(s["src"]))
        s["text"] = txt
        s["word_count"] = len(txt.split()) if txt else 0
        s["segments"] = segs
        del s["src"]
        print(f"  Scene audio {s['id']} ({s['duration_hms']}): {s['word_count']}w", flush=True)
    print(f"  Audio transcription finished in {time.time()-t2:.1f}s", flush=True)

    # 4. Probe, thumbnail, transcribe, and assemble the 5 MOV videos
    t3 = time.time()
    mov_files = sorted(
        [p for p in SRC_ROOT.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".mov", ".mp4")],
        key=lambda p: natural_key(p.name),
    )
    print(f"=== [4/5] Processing {len(mov_files)} Videos (Chikara Bonus 11/23) ===", flush=True)
    norm_dir = EXPORTS_DIR / "_norm" / "CHIKARA_BONUS"
    norm_dir.mkdir(parents=True, exist_ok=True)

    bonus_shots = []
    concat_lines = []
    cam_full_txt = []
    cam_full_srt = []
    srt_idx = 1
    cum = 0.0

    for idx, p in enumerate(mov_files, 1):
        meta = probe_media(p)
        stem = p.stem
        wav_p = WAV_TMP_DIR / f"{stem}.wav"
        if not wav_p.exists():
            subprocess.run([FFMPEG, "-y", "-i", str(p), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_p), "-loglevel", "error"], check=True)
        txt, segs = transcribe_file(wav_p)

        # Save per-shot transcripts
        (TRANSCRIPTS_DIR / "CHIKARA_BONUS" / f"{stem}.json").write_text(
            json.dumps({"camera": "CHIKARA_BONUS", "shot": stem, "duration": meta["duration"], "creation_time": meta["creation_time"], "text": txt, "segments": segs}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (TRANSCRIPTS_DIR / "CHIKARA_BONUS" / f"{stem}.txt").write_text(
            "\n".join(f"[{fmt_hms(s['start'])} -> {fmt_hms(s['end'])}] {s['text']}" for s in segs) + "\n",
            encoding="utf-8",
        )
        (TRANSCRIPTS_DIR / "CHIKARA_BONUS" / f"{stem}.srt").write_text(
            "\n".join(f"{k}\n{fmt_srt_ts(s['start'])} --> {fmt_srt_ts(s['end'])}\n{s['text']}\n" for k, s in enumerate(segs, 1)),
            encoding="utf-8",
        )

        # Thumbnail
        thumb_p = THUMBS_DIR / "CHIKARA_BONUS" / f"{stem}.jpg"
        seek = min(max(meta["duration"] * 0.15, 0.5), max(meta["duration"] - 0.5, 0.0))
        vf_th = (
            "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black,"
            "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuvj420p"
            if meta.get("is_hdr")
            else "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black,format=yuvj420p"
        )
        subprocess.run([FFMPEG, "-y", "-ss", f"{seek:.2f}", "-i", str(p), "-frames:v", "1", "-vf", vf_th, "-q:v", "3", str(thumb_p), "-loglevel", "error"], check=False)

        # Normalize to 1080p SDR BT.709 for YouTube master
        norm_p = norm_dir / f"{idx:03d}_{stem}.mp4"
        if not norm_p.exists():
            vf_n = (
                "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
                "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,fps=30"
                if meta.get("is_hdr")
                else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p,fps=30"
            )
            subprocess.run(
                [
                    FFMPEG, "-y", "-i", str(p), "-vf", vf_n,
                    "-c:v", "h264_videotoolbox", "-b:v", "6500k", "-profile:v", "high",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart", str(norm_p), "-loglevel", "error",
                ],
                check=True,
            )

        norm_dur = probe_media(norm_p)["duration"]
        safe_path = str(norm_p).replace("'", "'\\''")
        concat_lines.append(f"file '{safe_path}'")

        bonus_shots.append({
            "camera": "CHIKARA_BONUS",
            "filename": p.name,
            "stem": stem,
            "shot_index": idx,
            "camera_offset": round(cum, 3),
            "master_offset": round(cum, 3),
            "master_duration": round(norm_dur, 3),
            "master_ts": fmt_hms(cum),
            "thumb": f"assets/thumbs/CHIKARA_BONUS/{stem}.jpg",
            "transcript_txt": f"transcripts/CHIKARA_BONUS/{stem}.txt",
            "transcript_srt": f"transcripts/CHIKARA_BONUS/{stem}.srt",
            "transcript_json": f"transcripts/CHIKARA_BONUS/{stem}.json",
            "language": "en",
            "word_count": len(txt.split()) if txt else 0,
            "text": txt,
            "segments": segs,
            **meta,
        })

        cam_full_txt.append(f"\n=== SHOT {idx:02d}: {p.name} @ {fmt_hms(cum)} ({fmt_hms(norm_dur)}) ===")
        for seg in segs:
            gs, ge = cum + seg["start"], cum + seg["end"]
            cam_full_txt.append(f"[{fmt_hms(gs)}] {seg['text']}")
            cam_full_srt.append(f"{srt_idx}\n{fmt_srt_ts(gs)} --> {fmt_srt_ts(ge)}\n{seg['text']}\n")
            srt_idx += 1

        cum += norm_dur
        print(f"  Video [{idx}/{len(mov_files)}] {p.name} ({fmt_hms(norm_dur)}, {len(txt.split())}w)", flush=True)

    (TRANSCRIPTS_DIR / "CHIKARA_BONUS_FULL.txt").write_text("\n".join(cam_full_txt).strip() + "\n", encoding="utf-8")
    (TRANSCRIPTS_DIR / "CHIKARA_BONUS_FULL.srt").write_text("\n".join(cam_full_srt), encoding="utf-8")

    concat_txt = norm_dir / "concat.txt"
    concat_txt.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    master_mp4 = EXPORTS_DIR / "PRECIPICE_CHIKARA_BONUS_MASTER_1080p.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", "-movflags", "+faststart", str(master_mp4), "-loglevel", "error"],
        check=True,
    )
    master_dur = probe_media(master_mp4)["duration"]
    hero_jpg = THUMBS_DIR / "HERO_CHIKARA_BONUS.jpg"
    subprocess.run(
        [FFMPEG, "-y", "-ss", f"{min(5.0, master_dur*0.2):.2f}", "-i", str(master_mp4), "-frames:v", "1", "-q:v", "2", str(hero_jpg), "-loglevel", "error"],
        check=True,
    )
    print(f"  Master ready: {master_mp4.name} ({master_mp4.stat().st_size/(1024*1024):.1f} MB, {fmt_hms(master_dur)}) in {time.time()-t3:.1f}s", flush=True)

    # 5. Update data/shots.json + write data/hightail_112326.json
    print("=== [5/5] Writing data/hightail_112326.json & updating data/shots.json ===", flush=True)
    shots_data = json.loads((DATA_DIR / "shots.json").read_text(encoding="utf-8"))
    shots_data["cameras"]["CHIKARA_BONUS"] = {
        "id": "CHIKARA_BONUS",
        "label": "Chikara 11/23 Reels",
        "shot_count": len(bonus_shots),
        "total_duration": round(sum(s["duration"] for s in bonus_shots), 3),
        "master_duration": round(master_dur, 3),
        "master_size_mb": round(master_mp4.stat().st_size / (1024 * 1024), 1),
        "hero_thumb": f"assets/thumbs/{hero_jpg.name}",
        "total_words": sum(s["word_count"] for s in bonus_shots),
        "full_transcript_txt": "transcripts/CHIKARA_BONUS_FULL.txt",
        "full_transcript_srt": "transcripts/CHIKARA_BONUS_FULL.srt",
        "shots": bonus_shots,
    }
    (DATA_DIR / "shots.json").write_text(json.dumps(shots_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ht_payload = {
        "source": "Hightail — Chikara Motomura (Rob's Precipice 112326.zip)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cast_stills_count": len(cast_stills),
        "voice_refs_count": len(voice_items),
        "scene_audio_count": len(scene_items),
        "cast_stills": cast_stills,
        "voice_refs": voice_items,
        "scene_audio": scene_items,
    }
    (DATA_DIR / "hightail_112326.json").write_text(json.dumps(ht_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nALL HIGHTAIL PROCESSING COMPLETE in {time.time()-t0:.1f}s!", flush=True)


if __name__ == "__main__":
    main()
