# PRECIPICE — Multi-Camera Dailies & Transcript Archive

**Directed by Rob Nilsson** · **Produced & Photographed by Zhan Petrov** · **ROB NILSSON ART FORMS**

Interactive Apple-designed dailies screening room, frame-accurate unlisted YouTube camera assemblies, and searchable word-for-word transcripts for **PRECIPICE**.

- **Live Website**: https://zhanpetrov.github.io/precipice-film/
- **Unlisted YouTube Playlist (PRECIPICE)**: https://www.youtube.com/playlist?list=PLcER0Yz7OUpU
- **YouTube Channel**: [ROB NILSSON ART FORMS](https://www.youtube.com/@robnilssonartforms)

## Archive Overview

| Camera | Shots | Runtime | Indexed Words | Transcripts |
| :--- | ---: | ---: | ---: | :--- |
| **Chicara Cam** | 17 | 2h 17m | 21,209 | [`CHICARA_CAM_FULL.txt`](transcripts/CHICARA_CAM_FULL.txt) · [`CHICARA_CAM_FULL.srt`](transcripts/CHICARA_CAM_FULL.srt) |
| **Rob Cam** | 55 | 2h 57m | 28,452 | [`ROB_CAM_FULL.txt`](transcripts/ROB_CAM_FULL.txt) · [`ROB_CAM_FULL.srt`](transcripts/ROB_CAM_FULL.srt) |
| **Secret Cam** | 1 | 1h 20m | 5,912 | [`SECRET_CAM_FULL.txt`](transcripts/SECRET_CAM_FULL.txt) · [`SECRET_CAM_FULL.srt`](transcripts/SECRET_CAM_FULL.srt) |
| **Total** | **73** | **6h 36m** | **55,573** | Per-shot `.json`, `.srt`, `.txt` in [`transcripts/`](transcripts/) |

## Repository Structure

```text
precipice-film/
├── index.html          # Apple Pro Studio screening room & transcript explorer
├── styles.css          # Dark / Light Apple design system
├── app.js              # YouTube IFrame API sync, chapter jumping, cross-camera search
├── data/
│   ├── shots.json      # Complete shot metadata, offsets, thumbnails & transcript segments
│   ├── chapters.json   # Frame-accurate YouTube chapter timelines per camera
│   └── youtube.json    # Unlisted YouTube video IDs & verified receipts
├── transcripts/
│   ├── CHICARA_CAM/    # Per-shot .txt, .srt, .json transcripts (17 shots)
│   ├── ROB_CAM/        # Per-shot .txt, .srt, .json transcripts (55 shots)
│   ├── SECRET_CAM/     # Per-shot .txt, .srt, .json transcripts (1 continuous take)
│   └── *_FULL.{txt,srt}# Full combined camera master transcripts & subtitles
├── assets/
│   ├── thumbs/         # Tone-mapped 16:9 shot thumbnails + 1080p camera hero frames
│   └── stills/         # On-set production stills
└── scripts/
    ├── download_drive.py        # Parallel Google Drive downloader (deduplicated)
    ├── probe_and_transcribe.py  # ffprobe + thumbnail extraction + MLX Whisper v3-turbo
    ├── concat_cameras.py        # VideoToolbox 1080p BT.709 camera assembly
    └── upload_youtube.py        # Unlisted YouTube Studio uploader with chapters & playlist
```
