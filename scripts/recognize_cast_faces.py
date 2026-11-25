#!/usr/bin/env python3
"""
Runs deep face detection & recognition (MTCNN + InceptionResnetV1 VGGFace2)
across all 339 Cast Stills, clusters unique people by 512-D cosine similarity,
matches against known PRECIPICE actor portraits where available, crops square
320x320 face avatars, cleans up the 33 Cast Voice References with real names/roles,
and writes data/cast_people.json.
Run via: /Users/studio/.local/bin/uv run --with facenet-pytorch --with scikit-learn --with pillow --with numpy python3 scripts/recognize_cast_faces.py
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import torch
from facenet_pytorch import InceptionResnetV1, MTCNN
from PIL import Image, ImageOps
from sklearn.cluster import AgglomerativeClustering

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STILLS_FULL_DIR = ROOT / "assets" / "cast_stills" / "full"
FACES_DIR = ROOT / "assets" / "cast_faces"
KNOWN_ACTORS_DIR = Path("/Users/studio/Desktop/helloworld/precipice-studio/assets/actors")

# Curated cast voice metadata parsed directly from the 1-minute voice reference transcripts
VOICE_CAST_META = {
    "ZOOM0001_Tr1": ("Cast Member #01", "Conference Guest"),
    "ZOOM0002_Tr1": ("Tiger Lily Dostolova", "Conference Guest"),
    "ZOOM0003_Tr1": ("Serge", "Tech Bro"),
    "ZOOM0004_Tr1": ("Timothy Glynyn", "Cast"),
    "ZOOM0005_Tr1": ("Cast Member #05", "Cast"),
    "ZOOM0006_Tr1": ("Andrei Tatarinov", "Cast"),
    "ZOOM0007_Tr1": ("Alex Miller", "Protector"),
    "ZOOM0008_Tr1": ("Jim Dietrich", "Alex's Buddy"),
    "ZOOM0009_Tr1": ("Antonia Kao", "Cast"),
    "ZOOM0010_Tr1": ("Mary Ann Heath", "Tenderloin Y Group"),
    "ZOOM0011_Tr1": ("Angela Cross", "Cast"),
    "ZOOM0012_Tr1": ("Ed (Take 1)", "Comedian"),
    "ZOOM0013_Tr1": ("Ed (Take 2)", "Comedian"),
    "ZOOM0014_Tr1": ("Jeff", "Cast"),
    "ZOOM0015_Tr1": ("Nick Mavrakis", "ICE Agent"),
    "ZOOM0016_Tr1": ("Ronald Nevin", "SFPD Commander"),
    "ZOOM0017_Tr1": ("Steven Turner", "Tactical Officer"),
    "ZOOM0018_Tr1": ("Thomas Steer", "ICE Officer"),
    "ZOOM0019_Tr1": ("Lance Walker", "Cast"),
    "ZOOM0020_Tr1": ("Lucian Jamie", "Billy's Stakeholder"),
    "ZOOM0021_Tr1": ("Damon Bell", "Bartender"),
    "ZOOM0022_Tr1": ("Ed Krendel", "Cast"),
    "ZOOM0023_Tr1": ("Dennis Demir", "Cast"),
    "ZOOM0024_Tr1": ("Ilya Fomin", "Protagonist"),
    "ZOOM0025_Tr1": ("Russell Murphy", "Bar Regular"),
    "ZOOM0026_Tr1": ("Billy Aguero", "Pool League Captain"),
    "ZOOM0027_Tr1": ("Cast Member #27", "Bar Patron"),
    "ZOOM0028_Tr1": ("Oscar Valdivieso", "Pro Pool Player"),
    "ZOOM0029_Tr1": ("Brady Pearson", "Comedian / Host"),
    "ZOOM0030_Tr1": ("Pam Benjamin", "Comedian"),
    "ZOOM0031_Tr1": ("Lauren Kraut", "Comedian"),
    "ZOOM0032_Tr1": ("Victoria Barajas (Vicky Beretta)", "Comedian"),
    "ZOOM0033_Tr1": ("Denis Rajchic", "Thursday Regular"),
    "ZOOM0034_Tr1": ("Shondi Jeter", "Revolutionary"),
}

KNOWN_ACTOR_FILE_MAP = {
    "BAR_PORTRAIT_MICKEY_DISEND.jpg": "Mickey Disend",
    "BAR_PORTRAIT_ROB_NILSSON.jpg": "Rob Nilsson",
    "BAR_PORTRAIT_RUSS_MURPHY.jpg": "Russell Murphy",
    "CHAR_RUSS_02_CONTEMPLATIVE_FRONT.jpg": "Russell Murphy",
    "CHAR_WA_ANTONIA_KAO.jpg": "Antonia Kao",
    "CHAR_KEN_02_DETENTION_CLOSEUP.jpg": "Ken Newman",
}


def img_num(stem: str) -> int:
    m = re.search(r"(\d+)", stem)
    return int(m.group(1)) if m else 0


def crop_square_avatar(img: Image.Image, box: list[float], out_path: Path, size: int = 320) -> None:
    w, h = img.size
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    side = max(bw, bh) * 1.65
    # Bias slightly upward to include hair & shoulders naturally
    cy = cy - bh * 0.05
    left = max(0, int(cx - side / 2))
    top = max(0, int(cy - side / 2))
    right = min(w, int(cx + side / 2))
    bottom = min(h, int(cy + side / 2))
    crop = img.crop((left, top, right, bottom))
    crop = ImageOps.fit(crop, (size, size), method=Image.Resampling.LANCZOS)
    crop.save(out_path, "JPEG", quality=86, optimize=True)


def main() -> None:
    t0 = time.time()
    FACES_DIR.mkdir(parents=True, exist_ok=True)
    device = torch.device("cpu")  # MTCNN is rock-solid on CPU; fast on M5 Max

    print("Loading MTCNN + InceptionResnetV1 (VGGFace2)...", flush=True)
    mtcnn = MTCNN(image_size=160, margin=24, keep_all=True, min_face_size=48, device=device)
    resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)

    # 1. Embed known reference portraits if available
    known_refs: list[tuple[str, np.ndarray]] = []
    if KNOWN_ACTORS_DIR.exists():
        for fname, actor_name in KNOWN_ACTOR_FILE_MAP.items():
            p = KNOWN_ACTORS_DIR / fname
            if not p.exists():
                continue
            try:
                im = ImageOps.exif_transpose(Image.open(p).convert("RGB"))
                boxes, probs = mtcnn.detect(im)
                if boxes is not None and len(boxes) > 0:
                    faces = mtcnn(im)
                    if faces is not None and len(faces) > 0:
                        best_i = int(np.argmax(probs))
                        with torch.no_grad():
                            emb = resnet(faces[best_i].unsqueeze(0)).numpy()[0]
                        emb = emb / (np.linalg.norm(emb) + 1e-9)
                        known_refs.append((actor_name, emb))
            except Exception:
                pass
    print(f"Loaded {len(known_refs)} known PRECIPICE actor face references.", flush=True)

    # 2. Detect & embed primary face in each of the 339 Cast Stills
    ht = json.loads((DATA_DIR / "hightail_112326.json").read_text(encoding="utf-8"))
    stills = ht["cast_stills"]

    detected = []
    no_face = []

    for idx, st in enumerate(stills, 1):
        img_path = ROOT / st["full"]
        if not img_path.exists():
            continue
        im = ImageOps.exif_transpose(Image.open(img_path).convert("RGB"))
        boxes, probs = mtcnn.detect(im)
        if boxes is None or len(boxes) == 0:
            no_face.append(st)
            continue

        faces = mtcnn(im)
        if faces is None or len(faces) == 0:
            no_face.append(st)
            continue

        # Pick largest high-confidence face as primary subject of the portrait
        scores = []
        for b, pr in zip(boxes, probs):
            area = max(0.0, (b[2] - b[0]) * (b[3] - b[1]))
            scores.append(area * (float(pr) if pr else 0.5))
        best_i = int(np.argmax(scores))
        if (probs[best_i] or 0) < 0.85:
            no_face.append(st)
            continue

        with torch.no_grad():
            emb = resnet(faces[best_i].unsqueeze(0)).numpy()[0]
        emb = emb / (np.linalg.norm(emb) + 1e-9)

        detected.append({
            "still": st,
            "num": img_num(st["id"]),
            "box": [round(float(x), 1) for x in boxes[best_i]],
            "prob": round(float(probs[best_i]), 4),
            "area": round(float((boxes[best_i][2] - boxes[best_i][0]) * (boxes[best_i][3] - boxes[best_i][1])), 1),
            "emb": emb,
        })
        if idx % 50 == 0 or idx == len(stills):
            print(f"  Embedded [{idx}/{len(stills)}] stills (faces found: {len(detected)}) in {time.time()-t0:.1f}s", flush=True)

    # 3. Cluster embeddings with Agglomerative Clustering (cosine distance)
    X = np.vstack([d["emb"] for d in detected])
    clustering = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=0.46,
    )
    labels = clustering.fit_predict(X)

    clusters: dict[int, list[dict]] = {}
    for d, lbl in zip(detected, labels):
        clusters.setdefault(int(lbl), []).append(d)

    # Sort clusters chronologically by earliest still number
    raw_clusters = sorted(clusters.values(), key=lambda grp: min(x["num"] for x in grp))

    # Merge any 1-2 photo side-profile split whose frame numbers lie inside an enclosing >=4-photo burst
    merged_clusters: list[list[dict]] = []
    main_clusters = [g for g in raw_clusters if len(g) >= 3]
    tiny_clusters = [g for g in raw_clusters if len(g) < 3]

    for tg in tiny_clusters:
        t_min = min(x["num"] for x in tg)
        t_max = max(x["num"] for x in tg)
        # Check if contained inside a main burst's frame span
        host = None
        for mg in main_clusters:
            m_min = min(x["num"] for x in mg)
            m_max = max(x["num"] for x in mg)
            if m_min <= t_min and t_max <= m_max:
                host = mg
                break
        if host is not None:
            host.extend(tg)
        else:
            merged_clusters.append(tg)

    sorted_clusters = sorted(main_clusters + merged_clusters, key=lambda grp: min(x["num"] for x in grp))

    # Build clean Person profiles
    people = []
    for p_idx, grp in enumerate(sorted_clusters, 1):
        grp.sort(key=lambda x: x["num"])
        # Compute centroid embedding
        centroid = np.mean([x["emb"] for x in grp], axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-9)

        # Pick best frontal hero photo (closest to centroid * high prob * large face area)
        best_item = max(
            grp,
            key=lambda x: float(np.dot(x["emb"], centroid)) * x["prob"] * (min(x["area"], 180000) ** 0.25),
        )
        avatar_name = f"person_{p_idx:02d}.jpg"
        avatar_path = FACES_DIR / avatar_name
        hero_im = ImageOps.exif_transpose(Image.open(ROOT / best_item["still"]["full"]).convert("RGB"))
        crop_square_avatar(hero_im, best_item["box"], avatar_path, size=320)

        # Check known PRECIPICE actor match
        matched_name = None
        matched_sim = 0.0
        for ref_name, ref_emb in known_refs:
            sim = float(np.dot(centroid, ref_emb))
            if sim > matched_sim:
                matched_sim = sim
                matched_name = ref_name
        verified_name = matched_name if matched_sim >= 0.62 else None

        people.append({
            "id": f"person_{p_idx:02d}",
            "index": p_idx,
            "name": verified_name or f"Cast Person #{p_idx:02d}",
            "verified_identity": verified_name is not None,
            "match_confidence": round(matched_sim, 3) if verified_name else None,
            "avatar": f"assets/cast_faces/{avatar_name}",
            "photo_count": len(grp),
            "first_still": grp[0]["still"]["filename"],
            "last_still": grp[-1]["still"]["filename"],
            "stills": [
                {
                    "id": x["still"]["id"],
                    "filename": x["still"]["filename"],
                    "thumb": x["still"]["thumb"],
                    "full": x["still"]["full"],
                }
                for x in grp
            ],
        })

    # 4. Separate Cast 1-Min Voice References (ZOOM0001-ZOOM0034) vs Scene Audio (ZOOM0035-ZOOM0047)
    all_audio = ht.get("voice_refs", []) + ht.get("scene_audio", [])
    clean_voice_refs = []
    clean_scene_audio = []

    for item in all_audio:
        iid = item["id"]
        if iid in VOICE_CAST_META:
            speaker, role = VOICE_CAST_META[iid]
            clean_voice_refs.append({
                **item,
                "speaker": speaker,
                "role": role,
            })
        else:
            clean_scene_audio.append(item)

    clean_voice_refs.sort(key=lambda x: img_num(x["id"]))
    clean_scene_audio.sort(key=lambda x: img_num(x["id"]))

    # Update hightail_112326.json with separated clean voice_refs & scene_audio
    ht["voice_refs_count"] = len(clean_voice_refs)
    ht["scene_audio_count"] = len(clean_scene_audio)
    ht["voice_refs"] = clean_voice_refs
    ht["scene_audio"] = clean_scene_audio
    (DATA_DIR / "hightail_112326.json").write_text(json.dumps(ht, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Link verified actor voice samples directly to matching Person cards
    voice_by_name = {v["speaker"].lower(): v for v in clean_voice_refs}
    for p in people:
        v = voice_by_name.get(p["name"].lower())
        if v:
            p["voice_sample"] = {
                "id": v["id"],
                "audio": v["audio"],
                "duration_hms": v["duration_hms"],
                "role": v["role"],
                "text": v["text"],
            }

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": "MTCNN + InceptionResnetV1 (VGGFace2 512-D Arc/FaceNet Cosine Clustering)",
        "total_stills_scanned": len(stills),
        "faces_detected": len(detected),
        "unmatched_stills": len(no_face),
        "unique_people_count": len(people),
        "people": people,
    }
    (DATA_DIR / "cast_people.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\n=== FACE RECOGNITION COMPLETE in {time.time()-t0:.1f}s ===", flush=True)
    print(f"Scanned {len(stills)} stills -> {len(detected)} faces -> {len(people)} unique people!", flush=True)
    for p in people:
        tag = f" [VERIFIED: {p['name']} ({p['match_confidence']})]" if p["verified_identity"] else ""
        print(f"  {p['id']}: {p['photo_count']:2d} photos ({p['first_still']}..{p['last_still']}){tag}", flush=True)


if __name__ == "__main__":
    main()
