#!/usr/bin/env python3
"""
Builds the PRECIPICE Signed Actor Releases archive from Vanessa Marrufo's
'Digital Release' email:
  1. Moves raw OCR JSON out of public data/ into gitignored raw/releases/
  2. Creates web-safe JPG previews in assets/releases/ with the private payment
     mailing address / phone / email band cleanly masked (originals stay intact in raw/releases/)
  3. Updates official legal spellings + signed release badges across data/cast_people.json
     and data/hightail_112326.json
  4. Writes public data/releases.json linking each release to its face avatar & voice sample
Run via: /Users/studio/.local/bin/uv run --with pillow python3 scripts/build_releases_archive.py
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
RAW_REL = ROOT / "raw" / "releases"
WEB_REL = ROOT / "assets" / "releases"
DATA_DIR = ROOT / "data"

# Canonical signed release ledger from Vanessa Marrufo's Nov 24, 2026 email + Vision OCR
RELEASES = [
    {"id": "rel_01", "legal_name": "Angela Cross", "file": "IMG_8845.jpeg", "date": "2026-11-23", "person_id": "person_11", "voice_id": "ZOOM0011_Tr1", "role": "Cast"},
    {"id": "rel_02", "legal_name": "Anubhav Ashok", "file": "IMG_8846.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": None, "role": "Cast / 360 Camera"},
    {"id": "rel_03", "legal_name": "Marianne Heath", "file": "IMG_8847.jpeg", "date": "2026-11-23", "person_id": "person_10", "voice_id": "ZOOM0010_Tr1", "role": "Tenderloin Y Group"},
    {"id": "rel_04", "legal_name": "Edward", "file": "IMG_8848.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": "ZOOM0013_Tr1", "role": "Comedian"},
    {"id": "rel_05", "legal_name": "Antonia Kao", "file": "IMG_8849.jpeg", "date": "2026-11-23", "person_id": "person_09", "voice_id": "ZOOM0009_Tr1", "role": "Cast"},
    {"id": "rel_06", "legal_name": "Maya Dostal (Tiger Lily)", "file": "IMG_8850.jpeg", "date": "2026-11-23", "person_id": "person_02", "voice_id": "ZOOM0002_Tr1", "role": "Conference Guest"},
    {"id": "rel_07", "legal_name": "Ronald Nevin", "file": "IMG_8851.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": "ZOOM0016_Tr1", "role": "SFPD Commander"},
    {"id": "rel_08", "legal_name": "Nick Mavrakis", "file": "IMG_8852.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": "ZOOM0015_Tr1", "role": "ICE Agent"},
    {"id": "rel_09", "legal_name": "Lydia Becker", "file": "IMG_8853.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": None, "role": "Cast"},
    {"id": "rel_10", "legal_name": "Timofey Glinin", "file": "IMG_8854.jpeg", "date": "2026-11-23", "person_id": "person_04", "voice_id": "ZOOM0004_Tr1", "role": "Cast"},
    {"id": "rel_11", "legal_name": "Oscar Valdiviezo", "file": "IMG_8855.jpeg", "date": "2026-11-23", "person_id": "person_29", "voice_id": "ZOOM0028_Tr1", "role": "Pro Pool Player"},
    {"id": "rel_12", "legal_name": "Pam Benjamin", "file": "IMG_8856.jpeg", "date": "2026-11-23", "person_id": "person_31", "voice_id": "ZOOM0030_Tr1", "role": "Comedian"},
    {"id": "rel_13", "legal_name": "Denis Rajcic", "file": "IMG_8857.jpeg", "date": "2026-11-23", "person_id": "person_34", "voice_id": "ZOOM0033_Tr1", "role": "Thursday Regular"},
    {"id": "rel_14", "legal_name": "Loren Kraut", "file": "IMG_8858.jpeg", "date": "2026-11-23", "person_id": "person_32", "voice_id": "ZOOM0031_Tr1", "role": "Comedian"},
    {"id": "rel_15", "legal_name": "Sergei Solovev", "file": "IMG_8859.jpeg", "date": "2026-11-23", "person_id": "person_03", "voice_id": "ZOOM0003_Tr1", "role": "Tech Bro"},
    {"id": "rel_16", "legal_name": "William (Billy Aguero)", "file": "IMG_8860.jpeg", "date": "2026-11-23", "person_id": "person_27", "voice_id": "ZOOM0026_Tr1", "role": "Pool League Captain", "drive_pending": True},
    {"id": "rel_17", "legal_name": "Jim Dietrich", "file": "IMG_8861.jpeg", "date": "2026-11-23", "person_id": "person_08", "voice_id": "ZOOM0008_Tr1", "role": "Alex's Buddy", "drive_pending": True},
    {"id": "rel_18", "legal_name": "Alex Miller", "file": "IMG_8862.jpeg", "date": "2026-11-23", "person_id": "person_07", "voice_id": "ZOOM0007_Tr1", "role": "Protector", "drive_pending": True},
    {"id": "rel_19", "legal_name": "Brady Pearson", "file": "IMG_8863.jpeg", "date": "2026-11-23", "person_id": "person_30", "voice_id": "ZOOM0029_Tr1", "role": "Comedian / Host", "drive_pending": True},
    {"id": "rel_20", "legal_name": "Vikki Beretta (Victoria Barajas)", "file": "IMG_8865.jpeg", "date": "2026-11-23", "person_id": "person_33", "voice_id": "ZOOM0032_Tr1", "role": "Comedian"},
    {"id": "rel_21", "legal_name": "Andrei Tatarinov", "file": "IMG_8866.jpeg", "date": "2026-11-23", "person_id": "person_06", "voice_id": "ZOOM0006_Tr1", "role": "Cast"},
    {"id": "rel_22", "legal_name": "Stephen Turner", "file": "IMG_8867.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": "ZOOM0017_Tr1", "role": "Tactical Officer"},
    {"id": "rel_23", "legal_name": "Thomas Stier", "file": "IMG_8868.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": "ZOOM0018_Tr1", "role": "ICE Officer"},
    {"id": "rel_24", "legal_name": "Chaundi Perry Jeter", "file": "IMG_8869.jpeg", "date": "2026-11-23", "person_id": "person_35", "voice_id": "ZOOM0034_Tr1", "role": "Revolutionary"},
    {"id": "rel_25", "legal_name": "Lance Walker", "file": "IMG_8870.jpeg", "date": "2026-11-23", "person_id": None, "voice_id": "ZOOM0019_Tr1", "role": "Cast"},
]


def make_redacted_web_copy(src: Path, dst: Path) -> None:
    im = ImageOps.exif_transpose(Image.open(src).convert("RGB"))
    # Resize cleanly to max 1100px wide for fast mobile loading
    if im.width > 1100:
        ratio = 1100 / im.width
        im = im.resize((1100, int(im.height * ratio)), Image.Resampling.LANCZOS)

    w, h = im.size
    # Mask the private residential/mailing address, phone, and email block (y = 21%..40%)
    y1, y2 = int(h * 0.21), int(h * 0.40)
    x1, x2 = int(w * 0.04), int(w * 0.96)
    region = im.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(radius=28))
    im.paste(region, (x1, y1))

    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle([x1, y1, x2, y2], radius=14, fill=(20, 20, 24, 215), outline=(255, 255, 255, 45), width=2)
    label = "PRIVATE ADDRESS / CONTACT REDACTED FOR WEB ARCHIVE (ORIGINAL ON T7 SHIELD)"
    draw.text((w // 2, (y1 + y2) // 2), label, fill=(220, 220, 226, 255), anchor="mm")
    im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    im.save(dst, "JPEG", quality=80, optimize=True)


def main() -> None:
    # 1. Move raw OCR JSON out of tracked data/ so zero PII enters git
    ocr_public = DATA_DIR / "releases_ocr.json"
    if ocr_public.exists():
        shutil.move(str(ocr_public), str(RAW_REL / "releases_ocr.json"))
        print("Moved data/releases_ocr.json -> raw/releases/releases_ocr.json (gitignored)")

    WEB_REL.mkdir(parents=True, exist_ok=True)
    cp = json.loads((DATA_DIR / "cast_people.json").read_text(encoding="utf-8"))
    ht = json.loads((DATA_DIR / "hightail_112326.json").read_text(encoding="utf-8"))

    people_by_id = {p["id"]: p for p in cp["people"]}
    voices_by_id = {v["id"]: v for v in ht["voice_refs"]}

    out_releases = []
    scans_ready = 0

    for r in RELEASES:
        src = RAW_REL / r["file"]
        web_rel_path = None
        if src.exists() and src.stat().st_size > 10_000:
            dst = WEB_REL / f"{Path(r['file']).stem}.jpg"
            make_redacted_web_copy(src, dst)
            web_rel_path = f"assets/releases/{dst.name}"
            scans_ready += 1

        person = people_by_id.get(r["person_id"]) if r["person_id"] else None
        voice = voices_by_id.get(r["voice_id"]) if r["voice_id"] else None

        # Sync exact legal spelling + signed release badge onto Person & Voice records
        if person:
            person["name"] = r["legal_name"]
            person["role"] = r["role"]
            person["release_signed"] = True
            person["release_date"] = r["date"]
            if web_rel_path:
                person["release_img"] = web_rel_path
        if voice:
            voice["speaker"] = r["legal_name"]
            voice["role"] = r["role"]
            voice["release_signed"] = True
            if web_rel_path:
                voice["release_img"] = web_rel_path

        out_releases.append({
            "id": r["id"],
            "legal_name": r["legal_name"],
            "role": r["role"],
            "signed": True,
            "date_signed": r["date"],
            "source_file": r["file"],
            "scan_available": web_rel_path is not None,
            "drive_share_pending": bool(r.get("drive_pending")),
            "release_img": web_rel_path,
            "person_id": r["person_id"],
            "avatar": person["avatar"] if person else None,
            "photo_count": person["photo_count"] if person else 0,
            "voice_id": r["voice_id"],
            "voice_audio": voice["audio"] if voice else None,
            "voice_duration": voice["duration_hms"] if voice else None,
        })

    (DATA_DIR / "cast_people.json").write_text(json.dumps(cp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (DATA_DIR / "hightail_112326.json").write_text(json.dumps(ht, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    payload = {
        "source": "Vanessa Marrufo — 'Digital Release' Email (Nov 24, 2026)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_signed": len(out_releases),
        "scans_archived": scans_ready,
        "scans_pending_drive_share": len(out_releases) - scans_ready,
        "releases": out_releases,
    }
    (DATA_DIR / "releases.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Built releases archive: {len(out_releases)} signed actors ({scans_ready} PII-redacted web scans ready)!")


if __name__ == "__main__":
    main()
