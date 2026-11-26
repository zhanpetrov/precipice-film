#!/usr/bin/env python3
"""
Scans ALL 7 PRECIPICE camera master videos (10.85 hours) with deep face recognition
(MTCNN + InceptionResnetV1 VGGFace2) against all 35 recognized Cast People centroids
(plus Rob Nilsson & Mickey Disend), matching every on-screen appearance with exact
camera, timestamp, shot filename, and transcript snippet.
Updates data/cast_people.json so clicking any person shows ALL footage with them.
Run via: /Users/studio/.local/bin/uv run --with facenet-pytorch --with pillow --with numpy python3 scripts/scan_footage_faces.py
"""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from facenet_pytorch import InceptionResnetV1, MTCNN
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EXPORTS_DIR = ROOT / "exports"
SCAN_DIR = ROOT / "raw" / "_face_scan_frames"
FFMPEG = "/Users/studio/.local/bin/ffmpeg"

CAMERAS = [
    "CHICARA_CAM",
    "ROB_CAM",
    "SECRET_CAM",
    "ZHAN_CAM",
    "CHIKARA_BONUS",
    "DAY2_ROB_CAM",
    "DAY2_ZHAN_CAM",
]

SAMPLE_STEP_SEC = 10  # 1 frame every 10 seconds across 10.85 hours (~3,900 frames)
MATCH_THRESHOLD = 0.57
MERGE_GAP_SEC = 30


def fmt_hms(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def extract_frames_for_cam(cam: str) -> tuple[str, list[Path]]:
    mp4 = EXPORTS_DIR / f"PRECIPICE_{cam}_MASTER_1080p.mp4"
    out_dir = SCAN_DIR / cam
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("f_*.jpg"))
    if existing:
        return cam, existing
    if not mp4.exists():
        return cam, []
    subprocess.run(
        [
            FFMPEG, "-y", "-hwaccel", "videotoolbox", "-i", str(mp4),
            "-vf", f"fps=1/{SAMPLE_STEP_SEC},scale=640:-2",
            "-q:v", "4", str(out_dir / "f_%05d.jpg"), "-loglevel", "error",
        ],
        check=True,
    )
    return cam, sorted(out_dir.glob("f_*.jpg"))


def find_shot_and_snippet(cam_obj: dict, sec: float) -> tuple[dict | None, str]:
    shots = cam_obj.get("shots", [])
    hit = shots[0] if shots else None
    for s in shots:
        off = float(s.get("master_offset", s.get("camera_offset", 0)))
        if sec >= off - 0.5:
            hit = s
        else:
            break
    if not hit:
        return None, ""
    rel = sec - float(hit.get("master_offset", hit.get("camera_offset", 0)))
    # Find nearest transcript segment
    best_txt = ""
    for seg in hit.get("segments", []):
        if seg["start"] - 3 <= rel <= seg["end"] + 4:
            best_txt = seg["text"]
            break
    if not best_txt:
        best_txt = (hit.get("text") or "")[:90]
    return hit, best_txt[:110]


def main() -> None:
    t0 = time.time()
    device = torch.device("cpu")
    print("=== [1/4] Extracting 1 frame / 10s across all 7 camera masters in parallel ===", flush=True)
    cam_frames: dict[str, list[Path]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for cam, frames in ex.map(extract_frames_for_cam, CAMERAS):
            cam_frames[cam] = frames
            print(f"  {cam:15s}: {len(frames):4d} frames", flush=True)
    total_frames = sum(len(v) for v in cam_frames.values())
    print(f"Extracted {total_frames} frames total in {time.time()-t0:.1f}s.", flush=True)

    print("=== [2/4] Computing 512-D reference centroids for all 35 Cast People ===", flush=True)
    mtcnn = MTCNN(image_size=160, margin=20, keep_all=True, min_face_size=36, device=device)
    resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)

    cp = json.loads((DATA_DIR / "cast_people.json").read_text(encoding="utf-8"))
    shots_data = json.loads((DATA_DIR / "shots.json").read_text(encoding="utf-8"))
    yt_data = json.loads((DATA_DIR / "youtube.json").read_text(encoding="utf-8"))

    person_ids = []
    centroids = []
    for p in cp["people"]:
        embs = []
        # Use up to 5 stills per person to build an ultra-accurate centroid
        sample_stills = p["stills"][:5]
        for st in sample_stills:
            sp = ROOT / st["full"]
            if not sp.exists():
                continue
            try:
                im = ImageOps.exif_transpose(Image.open(sp).convert("RGB"))
                faces = mtcnn(im)
                if faces is not None and len(faces) > 0:
                    with torch.no_grad():
                        e = resnet(faces[0].unsqueeze(0)).numpy()[0]
                    e = e / (np.linalg.norm(e) + 1e-9)
                    embs.append(e)
            except Exception:
                pass
        if not embs:
            # Fallback to cropped avatar
            av = ROOT / p["avatar"]
            if av.exists():
                im = Image.open(av).convert("RGB").resize((160, 160))
                arr = (np.asarray(im, dtype=np.float32) - 127.5) / 128.0
                ten = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
                with torch.no_grad():
                    e = resnet(ten).numpy()[0]
                e = e / (np.linalg.norm(e) + 1e-9)
                embs.append(e)
        if embs:
            c = np.mean(embs, axis=0)
            c = c / (np.linalg.norm(c) + 1e-9)
            person_ids.append(p["id"])
            centroids.append(c)

    C = np.vstack(centroids)  # (N_people, 512)
    print(f"Built {len(person_ids)} cast centroids in {time.time()-t0:.1f}s.", flush=True)

    print("=== [3/4] Scanning all footage frames for cast faces ===", flush=True)
    # raw_hits[person_id][cam] = list of (sec, sim)
    raw_hits: dict[str, dict[str, list[tuple[int, float]]]] = {pid: {} for pid in person_ids}

    scanned = 0
    total_face_matches = 0
    for cam in CAMERAS:
        frames = cam_frames.get(cam, [])
        if not frames:
            continue
        cam_t0 = time.time()
        cam_matches = 0
        for idx, fp in enumerate(frames):
            sec = idx * SAMPLE_STEP_SEC
            scanned += 1
            try:
                im = Image.open(fp).convert("RGB")
                boxes, probs = mtcnn.detect(im)
                if boxes is None or len(boxes) == 0:
                    continue
                faces = mtcnn(im)
                if faces is None or len(faces) == 0:
                    continue
                valid_tensors = []
                for f_i, pr in enumerate(probs):
                    if f_i < len(faces) and pr is not None and float(pr) >= 0.90:
                        valid_tensors.append(faces[f_i])
                if not valid_tensors:
                    continue
                batch = torch.stack(valid_tensors)
                with torch.no_grad():
                    embs = resnet(batch).numpy()
                norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9
                embs = embs / norms
                sims = embs @ C.T  # (n_faces, n_people)
                for row in sims:
                    best_j = int(np.argmax(row))
                    best_sim = float(row[best_j])
                    if best_sim >= MATCH_THRESHOLD:
                        pid = person_ids[best_j]
                        raw_hits[pid].setdefault(cam, []).append((sec, best_sim))
                        cam_matches += 1
                        total_face_matches += 1
            except Exception:
                continue
        print(f"  [{cam:15s}] scanned {len(frames):4d} frames -> {cam_matches:4d} cast face hits in {time.time()-cam_t0:.1f}s", flush=True)

    print(f"=== [4/4] Grouping appearances & updating data/cast_people.json ({total_face_matches} raw hits) ===", flush=True)
    for p in cp["people"]:
        pid = p["id"]
        cam_map = raw_hits.get(pid, {})
        appearances = []
        for cam in CAMERAS:
            hits = sorted(cam_map.get(cam, []), key=lambda x: x[0])
            if not hits:
                continue
            cam_obj = shots_data["cameras"].get(cam)
            if not cam_obj:
                continue
            yt_id = yt_data.get(cam, {}).get("video_id", "")

            # Group contiguous timestamps within MERGE_GAP_SEC
            groups = []
            cur = [hits[0]]
            for h in hits[1:]:
                if h[0] - cur[-1][0] <= MERGE_GAP_SEC:
                    cur.append(h)
                else:
                    groups.append(cur)
                    cur = [h]
            groups.append(cur)

            for g in groups:
                start_s = g[0][0]
                end_s = g[-1][0] + SAMPLE_STEP_SEC
                peak_sim = max(x[1] for x in g)
                shot, snip = find_shot_and_snippet(cam_obj, start_s)
                appearances.append({
                    "camera": cam,
                    "camera_label": cam_obj["label"],
                    "video_id": yt_id,
                    "start": start_s,
                    "end": end_s,
                    "ts": fmt_hms(start_s),
                    "confidence": round(peak_sim, 3),
                    "hits": len(g),
                    "shot_index": shot["shot_index"] if shot else 1,
                    "shot_filename": shot["filename"] if shot else "",
                    "thumb": shot["thumb"] if shot else cam_obj.get("hero_thumb", ""),
                    "snippet": snip,
                })

        # Sort by highest confidence / multi-frame presence, keeping chronological order within camera
        appearances.sort(key=lambda a: (CAMERAS.index(a["camera"]), a["start"]))
        p["appearances"] = appearances
        p["appearance_count"] = len(appearances)

    cp["footage_scan"] = {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cameras_scanned": len(CAMERAS),
        "frames_scanned": scanned,
        "sample_step_sec": SAMPLE_STEP_SEC,
        "total_appearances": sum(p.get("appearance_count", 0) for p in cp["people"]),
    }
    (DATA_DIR / "cast_people.json").write_text(json.dumps(cp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nDONE in {time.time()-t0:.1f}s! Total appearances across all 7 cameras: {cp['footage_scan']['total_appearances']}", flush=True)
    for p in cp["people"]:
        print(f"  {p['id']} ({p['name']:32s}): {p['appearance_count']:3d} clips", flush=True)


if __name__ == "__main__":
    main()
