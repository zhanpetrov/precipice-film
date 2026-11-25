#!/usr/bin/env python3
"""
Uploads all 3 PRECIPICE camera master videos (CHICARA_CAM, ROB_CAM, SECRET_CAM)
strictly as UNLISTED to ROB NILSSON ART FORMS (UCFVsk5TWJPDgA6UKyEbn3sQ),
assigns each to the official PRECIPICE playlist (PLcER0Yz7OUpU),
populates frame-accurate CHAPTERS in each description, attaches custom 1920x1080
thumbnails, and verifies unauthenticated "isUnlisted":true + oEmbed HTTP 200.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

FORBIDDEN_RU_FLAG = "\U0001f1f7\U0001f1fa"
CHANNEL_ID = "UCFVsk5TWJPDgA6UKyEbn3sQ"  # ROB NILSSON ART FORMS (@robnilssonartforms)
PLAYLIST_ID = "PLcER0Yz7OUpU"
PLAYLIST_URL = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EXPORTS_DIR = ROOT / "exports"
THUMBS_DIR = ROOT / "assets" / "thumbs"
YOUTUBE_JSON = DATA_DIR / "youtube.json"
CHAPTERS_JSON = DATA_DIR / "chapters.json"

KNOWN_PREV_IDS = {
    "WnCSXFsJFh8", "RxiiSR6sZyQ", "sokfqTz0Gfk", "zRTcxtOp6uQ",
    "RSpq_N81OVg", "XWTjWcdDFKE", "2bRTsNsPiZA", "Qc9e2E2PKK8",
    "rZFMAM0z19s", "gu-eSpMYv5k", "f-DT6I0NT-I", "zwmOQKat4CM",
    "ypIVAC28RlU",
}


def guard_text(s: str) -> str:
    s = s.replace("<", "(").replace(">", ")").replace(FORBIDDEN_RU_FLAG, "")
    assert FORBIDDEN_RU_FLAG not in s, "Forbidden flag sequence detected!"
    assert "<" not in s and ">" not in s, "YouTube metadata cannot contain < or >!"
    return s


def fmt_yt_ts(sec: float, force_hours: bool = False) -> str:
    sec = max(0, int(round(sec)))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if force_hours or h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def clean_snippet(text: str, max_len: int = 44) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = t.replace("<", "").replace(">", "").replace(FORBIDDEN_RU_FLAG, "")
    if not t:
        return "Ambient / Camera Roll"
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rsplit(" ", 1)[0].rstrip(",.;:- ")
    return (cut or t[:max_len]) + "..."


def build_chapters_for_camera(cam: str, cam_info: dict) -> list[dict]:
    shots = cam_info["shots"]
    total_dur = float(cam_info.get("master_duration") or cam_info.get("total_duration") or 0)
    force_hours = total_dur >= 3600

    chapters: list[dict] = []

    if len(shots) == 1:
        # Single continuous shot (e.g. SECRET_CAM): create clean ~2.5-minute content chapters from transcript
        s = shots[0]
        segs = s.get("segments", [])
        interval = max(120, int(total_dur / 16)) if total_dur > 300 else 60
        last_t = -999
        # Always 00:00
        first_snip = clean_snippet(segs[0]["text"] if segs else s["text"], 52)
        chapters.append({
            "time": 0,
            "ts": fmt_yt_ts(0, force_hours),
            "title": f"{s['stem']} Start — {first_snip}",
            "shot_index": 1,
            "filename": s["filename"],
        })
        last_t = 0
        for seg in segs:
            st = int(round(seg["start"]))
            if st - last_t >= interval and total_dur - st >= 15:
                snip = clean_snippet(seg["text"], 54)
                chapters.append({
                    "time": st,
                    "ts": fmt_yt_ts(st, force_hours),
                    "title": snip,
                    "shot_index": 1,
                    "filename": s["filename"],
                })
                last_t = st
        return chapters

    # Multi-shot camera: 1 chapter per shot, respecting YouTube's >=10s spacing rule
    last_t = -999
    for s in shots:
        t = int(round(float(s.get("master_offset", s.get("camera_offset", 0)))))
        if not chapters:
            t = 0
        elif t - last_t < 10:
            # Shot started <10s after previous chapter; skip creating a separate YT chapter so YT doesn't invalidate the chapter bar
            continue
        snip = clean_snippet(s.get("text", ""), 38)
        chapters.append({
            "time": t,
            "ts": fmt_yt_ts(t, force_hours),
            "title": f"Shot {s['shot_index']:02d} ({s['stem']}) — {snip}",
            "shot_index": s["shot_index"],
            "filename": s["filename"],
        })
        last_t = t

    return chapters


def build_description(cam: str, cam_info: dict, chapters: list[dict]) -> str:
    label = cam_info["label"]
    n_shots = cam_info["shot_count"]
    dur_str = fmt_yt_ts(float(cam_info.get("master_duration") or cam_info.get("total_duration") or 0))
    total_words = cam_info.get("total_words", 0)

    header = (
        f"PRECIPICE — {label} Complete Camera Assembly ({n_shots} {'shot' if n_shots == 1 else 'shots'} · {dur_str})\n\n"
        f"Complete chronological camera assembly from the PRECIPICE film shoot, directed by Rob Nilsson. "
        f"Every shot has been transcribed word-for-word ({total_words:,} words indexed) and published with interactive "
        f"chapter navigation and full-text search.\n\n"
        f"Interactive Dailies & Transcript Explorer: https://zhanpetrov.github.io/precipice-film/\n"
        f"GitHub Transcript Archive: https://github.com/zhanpetrov/precipice-film\n"
        f"PRECIPICE Unlisted Playlist: {PLAYLIST_URL}\n\n"
        f"CHAPTERS\n"
    )
    footer = (
        "\n\nFilm: PRECIPICE\n"
        "Director: Rob Nilsson\n"
        "Producer / DP: Zhan Petrov\n"
        "ROB NILSSON ART FORMS — Unlisted Production Archive"
    )

    # Fit strictly under YouTube's 5,000-char description limit
    budget = 4850 - len(header) - len(footer)
    ch_lines = []
    used = 0
    for ch in chapters:
        line = f"{ch['ts']} {ch['title']}"
        if used + len(line) + 1 > budget:
            # Trim title shorter if needed
            short_title = ch["title"][:42].rstrip()
            line = f"{ch['ts']} {short_title}"
            if used + len(line) + 1 > budget:
                break
        ch_lines.append(line)
        used += len(line) + 1

    return guard_text(header + "\n".join(ch_lines) + footer)


def run_jxa(jxa_code: str, timeout: int = 120) -> str:
    res = subprocess.run(
        ["osascript", "-l", "JavaScript", "-"],
        input=jxa_code,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if res.returncode != 0:
        raise RuntimeError(f"JXA error ({res.returncode}): {res.stderr.strip()}")
    return res.stdout.strip()


def find_nilsson_studio_tab() -> dict:
    raw = run_jxa(
        f"""
        (() => {{
          const chrome = Application("Google Chrome");
          const wins = chrome.windows();
          let fallback = null;
          for (let wi = 0; wi < wins.length; wi++) {{
            const w = wins[wi];
            const urls = w.tabs.url();
            const ids = w.tabs.id();
            const titles = w.tabs.title();
            for (let ti = 0; ti < urls.length; ti++) {{
              const u = urls[ti] || "";
              const t = titles[ti] || "";
              if (u.includes("studio.youtube.com") && u.includes("{CHANNEL_ID}")) {{
                const hit = {{ winId: w.id(), tabId: String(ids[ti]), url: u, title: t }};
                if (!t.includes("Oops")) return JSON.stringify(hit);
                fallback = hit;
              }}
            }}
          }}
          if (fallback) return JSON.stringify(fallback);
          return JSON.stringify({{ error: "NOT_FOUND" }});
        }})()
        """,
        timeout=30,
    )
    info = json.loads(raw)
    if "winId" not in info:
        raise RuntimeError(f"Could not find ROB NILSSON ART FORMS Studio tab ({CHANNEL_ID}): {info}")
    return info


def nav_tab(win_id: int, tab_id: str, url: str) -> None:
    run_jxa(
        f"""
        (() => {{
          const chrome = Application("Google Chrome");
          const w = chrome.windows.byId({win_id});
          const ids = w.tabs.id().map(String);
          const idx = ids.indexOf({json.dumps(str(tab_id))});
          if (idx < 0) throw new Error("Tab not found: " + {json.dumps(str(tab_id))});
          w.activeTabIndex = idx + 1;
          w.tabs()[idx].url = {json.dumps(url)};
          return "OK";
        }})()
        """,
        timeout=30,
    )


def exec_tab_js(win_id: int, tab_id: str, js_body: str, timeout: int = 120) -> str:
    return run_jxa(
        f"""
        (() => {{
          const chrome = Application("Google Chrome");
          const w = chrome.windows.byId({win_id});
          const ids = w.tabs.id().map(String);
          const idx = ids.indexOf({json.dumps(str(tab_id))});
          if (idx < 0) throw new Error("Tab not found: " + {json.dumps(str(tab_id))});
          return w.tabs()[idx].execute({{ javascript: {json.dumps(js_body)} }});
        }})()
        """,
        timeout=timeout,
    )


def click_publish_anyway_if_present(win_id: int, tab_id: str) -> str:
    return exec_tab_js(
        win_id,
        tab_id,
        """
        (() => {
          const conf = document.querySelector("#confirmation-dialog");
          if (!conf) return "NO_CONF";
          const pubAnyway = [...conf.querySelectorAll("ytcp-button, button")].find(
            b => (b.innerText || "").trim() === "Publish anyway"
          );
          if (pubAnyway) {
            pubAnyway.click();
            const inner = (pubAnyway.shadowRoot && pubAnyway.shadowRoot.querySelector("button")) || pubAnyway.querySelector("button");
            if (inner) inner.click();
            return "CLICKED_PUBLISH_ANYWAY";
          }
          return "NO_BTN";
        })()
        """,
    )


def check_unauthenticated_unlisted(yt_id: str) -> tuple[bool, bool, str, str]:
    watch_url = f"https://www.youtube.com/watch?v={yt_id}"
    is_unlisted = False
    try:
        req = urllib.request.Request(watch_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html_txt = resp.read().decode("utf-8", errors="ignore")
            if '"isUnlisted":true' in html_txt:
                is_unlisted = True
    except Exception:
        pass

    oembed_ok = False
    oembed_title = ""
    oembed_author = ""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={watch_url}&format=json"
        oreq = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(oreq, timeout=15) as oresp:
            if oresp.status == 200:
                odata = json.loads(oresp.read().decode("utf-8"))
                oembed_ok = True
                oembed_title = str(odata.get("title") or "")
                oembed_author = str(odata.get("author_name") or "")
    except Exception:
        pass

    return is_unlisted, oembed_ok, oembed_title, oembed_author


def upload_one(
    win_id: int,
    tab_id: str,
    cam: str,
    mp4_path: Path,
    thumb_path: Path,
    title: str,
    description: str,
    seen_ids: set[str],
) -> dict:
    assert mp4_path.exists() and mp4_path.stat().st_size > 1_000_000, f"Invalid MP4: {mp4_path}"
    assert thumb_path.exists() and thumb_path.stat().st_size < 1_900_000, f"Invalid thumbnail: {thumb_path}"
    title = guard_text(title)
    description = guard_text(description)
    assert len(title) <= 100, f"Title too long ({len(title)}): {title}"

    upload_url = f"https://studio.youtube.com/channel/{CHANNEL_ID}/videos/upload?d=ud"
    print(f"\n[{cam}] [1/6] Navigating to {upload_url} ...", flush=True)
    nav_tab(win_id, tab_id, upload_url)
    time.sleep(6.5)

    cur_url = exec_tab_js(win_id, tab_id, "location.href")
    assert CHANNEL_ID in cur_url, f"SAFETY ABORT: Expected channel {CHANNEL_ID}, got {cur_url}"

    st0 = exec_tab_js(
        win_id,
        tab_id,
        """
        (() => {
          const inp = document.querySelector("input[type='file'][name='Filedata']") ||
                      document.querySelector("ytcp-uploads-file-picker input[type='file']");
          if (inp) return "READY";
          const createBtn = document.querySelector("button[aria-label='Create']") ||
            [...document.querySelectorAll("ytcp-button, button")].find(b => (b.innerText || "").trim() === "Create");
          if (createBtn) createBtn.click();
          return "CLICKED_CREATE";
        })()
        """,
    )
    if st0 == "CLICKED_CREATE":
        time.sleep(1.5)
        exec_tab_js(
            win_id,
            tab_id,
            """
            (() => {
              const items = [...document.querySelectorAll("tp-yt-paper-item, ytcp-ve, [role='menuitem']")];
              const up = items.find(el => (el.innerText || "").includes("Upload video"));
              if (up) up.click();
              return "CLICKED_UPLOAD";
            })()
            """,
        )
        time.sleep(2.5)

    total_bytes = mp4_path.stat().st_size
    print(f"[{cam}] [2/6] Attaching {total_bytes / (1024*1024):.1f} MB via real OS click + native file picker...", flush=True)

    # Put exact path on clipboard so spaces and '????' paste cleanly
    subprocess.run(["pbcopy"], input=str(mp4_path), text=True, check=True)

    # Bring Chrome window & Studio tab to front
    run_jxa(
        f"""
        (() => {{
          const chrome = Application("Google Chrome");
          chrome.activate();
          const w = chrome.windows.byId({win_id});
          w.index = 1;
          const ids = w.tabs.id().map(String);
          const idx = ids.indexOf({json.dumps(str(tab_id))});
          if (idx >= 0) w.activeTabIndex = idx + 1;
          return "ACTIVATED";
        }})()
        """,
        timeout=30,
    )
    time.sleep(0.8)

    # Get exact screen coordinates of #select-files-button
    coords_raw = exec_tab_js(
        win_id,
        tab_id,
        """
        (() => {
          const btn = document.querySelector("#select-files-button") ||
                      document.querySelector("ytcp-uploads-file-picker ytcp-button") ||
                      document.querySelector("ytcp-uploads-file-picker button");
          if (!btn) return JSON.stringify({ error: "NO_PICKER_BTN" });
          btn.scrollIntoView({ block: "center" });
          const r = btn.getBoundingClientRect();
          const topChrome = window.outerHeight - window.innerHeight;
          const leftChrome = Math.round((window.outerWidth - window.innerWidth) / 2);
          const sx = Math.round(window.screenX + leftChrome + r.left + r.width / 2);
          const sy = Math.round(window.screenY + topChrome + r.top + r.height / 2);
          return JSON.stringify({ x: sx, y: sy });
        })()
        """,
    )
    coords = json.loads(coords_raw)
    if "x" not in coords:
        raise RuntimeError(f"Could not locate Select Files button: {coords}")
    sx, sy = int(coords["x"]), int(coords["y"])
    print(f"[{cam}] [3/6] Clicking Select Files at screen ({sx}, {sy})...", flush=True)

    # Genuine OS-level click via CoreGraphics in JXA (satisfies Chrome user-gesture requirement)
    run_jxa(
        f"""
        ObjC.import('CoreGraphics');
        (() => {{
          const pt = {{ x: {sx}, y: {sy} }};
          const move = $.CGEventCreateMouseEvent(null, $.kCGEventMouseMoved, pt, $.kCGMouseButtonLeft);
          const down = $.CGEventCreateMouseEvent(null, $.kCGEventLeftMouseDown, pt, $.kCGMouseButtonLeft);
          const up   = $.CGEventCreateMouseEvent(null, $.kCGEventLeftMouseUp, pt, $.kCGMouseButtonLeft);
          $.CGEventPost($.kCGHIDEventTap, move);
          delay(0.15);
          $.CGEventPost($.kCGHIDEventTap, down);
          delay(0.08);
          $.CGEventPost($.kCGHIDEventTap, up);
          return "CLICKED_OS";
        }})()
        """,
        timeout=30,
    )

    # Wait up to 8s for macOS Open Sheet to appear
    sheet_open = False
    for _ in range(16):
        time.sleep(0.5)
        cnt = subprocess.check_output(
            ["osascript", "-e", 'tell application "System Events" to tell process "Google Chrome" to get count of sheets of window 1'],
            text=True,
        ).strip()
        if cnt.isdigit() and int(cnt) > 0:
            sheet_open = True
            break
    if not sheet_open:
        raise RuntimeError(f"Native macOS Open sheet did not appear after clicking ({sx}, {sy})")

    subprocess.run(
        [
            "osascript",
            "-e", 'tell application "Google Chrome" to activate',
            "-e", 'delay 0.3',
            "-e", 'tell application "System Events" to keystroke "g" using {command down, shift down}',
            "-e", 'delay 1.0',
            "-e", 'tell application "System Events" to keystroke "v" using {command down}',
            "-e", 'delay 0.6',
            "-e", 'tell application "System Events" to key code 36',
            "-e", 'delay 1.2',
            "-e", 'tell application "System Events" to key code 36',
        ],
        check=True,
    )
    print(f"[{cam}] [3/6] Selected {mp4_path.name} in native Open sheet", flush=True)

    yt_id = ""
    for _ in range(120):
        time.sleep(1.5)
        st = json.loads(
            exec_tab_js(
                win_id,
                tab_id,
                """
                (() => {
                  const dlg = document.querySelector("ytcp-uploads-dialog");
                  const bodyTxt = dlg ? dlg.innerText : document.body.innerText;
                  if (bodyTxt.includes("Daily upload limit reached")) {
                    return JSON.stringify({ error: "DAILY_UPLOAD_LIMIT_REACHED" });
                  }
                  const links = dlg ? [...dlg.querySelectorAll("a")].map(a => a.href).filter(h => h.includes("youtu.be/") || h.includes("youtube.com/watch")) : [];
                  const boxes = dlg ? dlg.querySelectorAll("#textbox[contenteditable='true']").length : 0;
                  return JSON.stringify({ links, boxes });
                })()
                """,
            )
        )
        if st.get("error"):
            raise RuntimeError(st["error"])
        if st.get("links") and st.get("boxes", 0) >= 2:
            m = re.search(r"(?:youtu\.be/|watch\?v=)([A-Za-z0-9_-]{11})", st["links"][0])
            if m and m.group(1) not in seen_ids:
                yt_id = m.group(1)
                break
    if not yt_id:
        raise RuntimeError(f"[{cam}] Timed out waiting for YouTube Studio to allocate Video ID")

    seen_ids.add(yt_id)
    yt_url = f"https://youtu.be/{yt_id}"
    watch_url = f"https://www.youtube.com/watch?v={yt_id}"
    playlist_watch_url = f"https://www.youtube.com/watch?v={yt_id}&list={PLAYLIST_ID}"
    print(f"[{cam}] [4/6] Allocated Video ID: {yt_id} -> {yt_url}", flush=True)

    thumb_b64 = base64.b64encode(thumb_path.read_bytes()).decode("ascii")
    meta_res = exec_tab_js(
        win_id,
        tab_id,
        f"""
        (() => {{
          const dlg = document.querySelector("ytcp-uploads-dialog") || document;
          const step0 = dlg.querySelector("#step-badge-0");
          if (step0) {{ try {{ step0.click(); }} catch (e) {{}} }}
          const boxes = [...dlg.querySelectorAll("#textbox[contenteditable='true']")];
          if (boxes.length >= 1) {{
            boxes[0].focus();
            document.execCommand("selectAll", false, null);
            document.execCommand("insertText", false, {json.dumps(title)});
            boxes[0].dispatchEvent(new Event("input", {{ bubbles: true }}));
          }}
          if (boxes.length >= 2) {{
            boxes[1].focus();
            document.execCommand("selectAll", false, null);
            document.execCommand("insertText", false, {json.dumps(description)});
            boxes[1].dispatchEvent(new Event("input", {{ bubbles: true }}));
          }}
          const tBin = atob({json.dumps(thumb_b64)});
          const tBytes = new Uint8Array(tBin.length);
          for (let i = 0; i < tBin.length; i++) tBytes[i] = tBin.charCodeAt(i);
          const tFile = new File([new Blob([tBytes], {{ type: "image/jpeg" }})], {json.dumps(thumb_path.name)}, {{ type: "image/jpeg" }});
          const tDt = new DataTransfer();
          tDt.items.add(tFile);
          const thumbInp = [...dlg.querySelectorAll("input[type='file']")].find(inp => (inp.accept || "").includes("image") || inp.id === "file-loader");
          let thumbAttached = false;
          if (thumbInp) {{
            thumbInp.files = tDt.files;
            thumbInp.dispatchEvent(new Event("change", {{ bubbles: true }}));
            thumbAttached = true;
          }}
          const notKids = dlg.querySelector("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']");
          if (notKids) {{
            notKids.click();
            const rc = (notKids.shadowRoot && notKids.shadowRoot.querySelector("#radioContainer")) || notKids.querySelector("#radioContainer");
            if (rc) rc.click();
          }}
          const toggleMore = dlg.querySelector("#toggle-button");
          if (toggleMore && (toggleMore.innerText || "").includes("Show more")) {{
            toggleMore.click();
            const tb = (toggleMore.shadowRoot && toggleMore.shadowRoot.querySelector("button")) || toggleMore.querySelector("button");
            if (tb) tb.click();
          }}
          return JSON.stringify({{ boxes: boxes.length, thumbAttached }});
        }})()
        """,
    )
    print(f"  [{cam}] Metadata & thumbnail set: {meta_res}", flush=True)
    time.sleep(1.5)

    pl_open = exec_tab_js(
        win_id,
        tab_id,
        """
        (() => {
          const dlg = document.querySelector("ytcp-uploads-dialog") || document;
          const synthNo = dlg.querySelector("tp-yt-paper-radio-button[name='VIDEO_HAS_ALTERED_CONTENT_NO']");
          if (synthNo) {
            synthNo.scrollIntoView({ block: "center" });
            synthNo.click();
            const rc = (synthNo.shadowRoot && synthNo.shadowRoot.querySelector("#radioContainer")) || synthNo.querySelector("#radioContainer");
            if (rc) rc.click();
          }
          const plComp = dlg.querySelector("ytcp-video-metadata-playlists");
          if (plComp) {
            plComp.scrollIntoView({ block: "center" });
            const trig = plComp.querySelector("ytcp-text-dropdown-trigger, #trigger, button, .dropdown-trigger-text");
            if (trig) { trig.click(); return "OPENED_PLAYLIST_DROPDOWN"; }
            plComp.click();
            return "CLICKED_PL_COMP";
          }
          return "NO_PL_COMP";
        })()
        """,
    )
    print(f"  [{cam}] Playlist dropdown: {pl_open}", flush=True)
    time.sleep(2.2)

    pl_sel = exec_tab_js(
        win_id,
        tab_id,
        """
        (() => {
          const plDlg = document.querySelector("ytcp-playlist-dialog");
          const root = plDlg || document;
          const labels = [...root.querySelectorAll("tp-yt-paper-checkbox, ytcp-checkbox-lit, li, label")];
          let matched = false;
          for (const el of labels) {
            const txt = (el.innerText || el.textContent || "").trim();
            if (txt === "PRECIPICE" || txt.split("\\n")[0].trim() === "PRECIPICE") {
              const isChecked = el.hasAttribute("checked") || el.getAttribute("aria-checked") === "true";
              if (!isChecked) {
                const cb = el.querySelector("#checkboxContainer, #checkbox, input") || el;
                cb.click();
              }
              matched = true;
              break;
            }
          }
          const doneBtn = root.querySelector("ytcp-button.done-button, #done-button, ytcp-button[label='Done']") ||
            [...root.querySelectorAll("ytcp-button, button")].find(b => (b.innerText || "").trim() === "Done");
          if (doneBtn) doneBtn.click();
          return JSON.stringify({ matched, hadDialog: !!plDlg });
        })()
        """,
    )
    print(f"  [{cam}] Playlist PRECIPICE selection: {pl_sel}", flush=True)
    time.sleep(1.3)

    for step_i in range(6):
        has_unl = exec_tab_js(
            win_id,
            tab_id,
            """
            (() => {
              const dlg = document.querySelector("ytcp-uploads-dialog");
              const unl = dlg ? dlg.querySelector("tp-yt-paper-radio-button[name='UNLISTED']") : null;
              if (unl) return "FOUND_UNLISTED";
              const nbWrap = dlg ? dlg.querySelector("#next-button") : null;
              const nbBtn = nbWrap
                ? ((nbWrap.shadowRoot && nbWrap.shadowRoot.querySelector("button")) || nbWrap.querySelector("button") || nbWrap)
                : null;
              if (nbBtn) {
                nbWrap.click();
                nbBtn.click();
                return "CLICKED_NEXT_BTN";
              }
              const sb3 = dlg ? dlg.querySelector("#step-badge-3") : null;
              if (sb3) { sb3.click(); return "CLICKED_BADGE_3"; }
              return "NO_NEXT";
            })()
            """,
        )
        if has_unl == "FOUND_UNLISTED":
            break
        if step_i == 3:
            exec_tab_js(
                win_id,
                tab_id,
                """
                (() => {
                  const dlg = document.querySelector("ytcp-uploads-dialog");
                  const sb3 = dlg ? dlg.querySelector("#step-badge-3") : null;
                  if (sb3) {
                    sb3.click();
                    const b = (sb3.shadowRoot && sb3.shadowRoot.querySelector("button")) || sb3.querySelector("button");
                    if (b) b.click();
                  }
                  return "FORCED_BADGE_3";
                })()
                """,
            )
        time.sleep(1.3)

    vis_raw = exec_tab_js(
        win_id,
        tab_id,
        """
        (() => {
          const dlg = document.querySelector("ytcp-uploads-dialog");
          const unl = dlg ? dlg.querySelector("tp-yt-paper-radio-button[name='UNLISTED']") : null;
          const pub = dlg ? dlg.querySelector("tp-yt-paper-radio-button[name='PUBLIC']") : null;
          if (unl) {
            unl.scrollIntoView({ block: "center" });
            unl.click();
            const rc = (unl.shadowRoot && unl.shadowRoot.querySelector("#radioContainer")) || unl.querySelector("#radioContainer");
            if (rc) rc.click();
          }
          return JSON.stringify({
            found: !!unl,
            checked: unl ? !!unl.checked : false,
            aria: unl ? unl.getAttribute("aria-checked") : null,
            pubAria: pub ? pub.getAttribute("aria-checked") : null
          });
        })()
        """,
    )
    vis = json.loads(vis_raw)
    print(f"[{cam}] [5/6] UNLISTED visibility verified: {vis}", flush=True)
    if (vis.get("aria") != "true" and not vis.get("checked")) or vis.get("pubAria") == "true":
        raise RuntimeError(f"PRIVACY GUARD ABORT: Failed to verify strictly UNLISTED: {vis}")

    for step in range(1800):
        done_st = json.loads(
            exec_tab_js(
                win_id,
                tab_id,
                """
                (() => {
                  const dlg = document.querySelector("ytcp-uploads-dialog");
                  if (!dlg) return JSON.stringify({ done: true, prog: "DIALOG_CLOSED" });
                  const progEl = dlg.querySelector("ytcp-video-upload-progress");
                  const prog = progEl ? (progEl.innerText || "").trim() : "";
                  if (prog.includes("Uploading")) return JSON.stringify({ done: false, prog });
                  const doneWrap = dlg.querySelector("#done-button");
                  const doneBtn = doneWrap
                    ? ((doneWrap.shadowRoot && doneWrap.shadowRoot.querySelector("button")) || doneWrap.querySelector("button") || doneWrap)
                    : null;
                  const dis = !doneWrap || doneWrap.disabled || doneWrap.getAttribute("aria-disabled") === "true";
                  if (doneBtn && !dis) {
                    doneWrap.click();
                    doneBtn.click();
                    return JSON.stringify({ done: true, prog });
                  }
                  return JSON.stringify({ done: false, prog });
                })()
                """,
            )
        )
        if step % 10 == 0 or done_st.get("done"):
            print(f"  [{cam} Upload {step*3}s] {done_st}", flush=True)
        if done_st.get("done"):
            break
        time.sleep(3.0)
    else:
        raise RuntimeError(f"[{cam}] Timed out waiting for YouTube upload completion")

    for _ in range(5):
        time.sleep(1.8)
        pa = click_publish_anyway_if_present(win_id, tab_id)
        if pa == "CLICKED_PUBLISH_ANYWAY":
            print(f"  [{cam}] Clicked 'Publish anyway'", flush=True)

    time.sleep(4.0)
    exec_tab_js(
        win_id,
        tab_id,
        """
        (() => {
          document.querySelectorAll("ytcp-video-share-dialog #close-button, ytcp-uploads-still-processing-dialog #close-button, #close-icon-button").forEach(b => {
            try { b.click(); } catch (e) {}
          });
          return "CLOSED_SHARE";
        })()
        """,
    )

    verified_unlisted = False
    verified_oembed = False
    oem_title = ""
    oem_author = ""
    for attempt in range(25):
        is_unl, oem_ok, oem_title, oem_author = check_unauthenticated_unlisted(yt_id)
        if is_unl:
            verified_unlisted = True
        if oem_ok:
            verified_oembed = True
        if verified_unlisted:
            print(
                f"[{cam}] [6/6] VERIFIED UNLISTED: {yt_url} "
                f"(isUnlisted={verified_unlisted}, oEmbed={verified_oembed}, author={oem_author!r})",
                flush=True,
            )
            break
        time.sleep(3.0)

    return {
        "camera": cam,
        "channel_name": "ROB NILSSON ART FORMS",
        "channel_id": CHANNEL_ID,
        "channel_url": "https://www.youtube.com/@robnilssonartforms",
        "video_id": yt_id,
        "youtu_be": yt_url,
        "watch_url": watch_url,
        "playlist_watch_url": playlist_watch_url,
        "playlist_id": PLAYLIST_ID,
        "playlist_url": PLAYLIST_URL,
        "playlist_selection": json.loads(pl_sel),
        "embed_url": f"https://www.youtube.com/embed/{yt_id}",
        "title": title,
        "visibility": "UNLISTED",
        "verified_is_unlisted": verified_unlisted,
        "verified_oembed": verified_oembed,
        "oembed_author": oem_author,
    }


def main() -> None:
    shots_data = json.loads((DATA_DIR / "shots.json").read_text(encoding="utf-8"))
    existing = json.loads(YOUTUBE_JSON.read_text(encoding="utf-8")) if YOUTUBE_JSON.exists() else {}
    seen_ids = set(KNOWN_PREV_IDS)
    for v in existing.values():
        if isinstance(v, dict) and v.get("video_id"):
            seen_ids.add(v["video_id"])

    cam_list = [c for c in ["CHICARA_CAM", "ROB_CAM", "SECRET_CAM", "CHIKARA_BONUS"] if c in shots_data["cameras"]]
    chapters_map = {}
    for cam in cam_list:
        chapters_map[cam] = build_chapters_for_camera(cam, shots_data["cameras"][cam])
    CHAPTERS_JSON.write_text(json.dumps(chapters_map, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {CHAPTERS_JSON} ({ {k: len(v) for k, v in chapters_map.items()} })", flush=True)

    yt_tab = find_nilsson_studio_tab()
    win_id = int(yt_tab["winId"])
    tab_id = str(yt_tab["tabId"])
    print(f"Bound to ROB NILSSON ART FORMS Studio tab: winId={win_id}, tabId={tab_id} ({yt_tab['title']})", flush=True)

    titles = {
        "CHICARA_CAM": "PRECIPICE — Chicara Cam (Complete Assembly, 17 Shots) | Rob Nilsson",
        "ROB_CAM": "PRECIPICE — Rob Cam (Complete Assembly, 55 Shots) | Rob Nilsson",
        "SECRET_CAM": "PRECIPICE — Secret Cam (Complete Uncut Take) | Rob Nilsson",
        "CHIKARA_BONUS": "PRECIPICE — Chikara 11/23 Reels (5 Shots) | Rob Nilsson",
    }

    for cam in cam_list:
        if cam in existing and existing[cam].get("video_id"):
            print(f"[{cam}] Already uploaded: {existing[cam]['youtu_be']} — skipping.", flush=True)
            continue
        mp4_path = EXPORTS_DIR / f"PRECIPICE_{cam}_MASTER_1080p.mp4"
        thumb_path = THUMBS_DIR / f"HERO_{cam}.jpg"
        desc = build_description(cam, shots_data["cameras"][cam], chapters_map[cam])
        receipt = upload_one(
            win_id, tab_id, cam, mp4_path, thumb_path, titles[cam], desc, seen_ids
        )
        existing[cam] = receipt
        YOUTUBE_JSON.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        time.sleep(3.0)

    print("\n=== ALL 3 CAMERAS UPLOADED TO ROB NILSSON ART FORMS (UNLISTED / PRECIPICE) ===", flush=True)
    print(json.dumps(existing, indent=2), flush=True)


if __name__ == "__main__":
    main()
