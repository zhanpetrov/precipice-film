#!/usr/bin/env python3
"""
Fetches all inline and attached signed Actor Release JPEG images from Vanessa Marrufo's
'Digital Release' email in the open Gmail Chrome tab and saves them to raw/releases/.
"""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "raw" / "releases"
WIN_ID = 1323614148
TAB_ID = "1323618324"


def exec_js(js: str, timeout: int = 120) -> str:
    jxa = f"""
    (() => {{
      const chrome = Application("Google Chrome");
      const w = chrome.windows.byId({WIN_ID});
      const ids = w.tabs.id().map(String);
      const idx = ids.indexOf({json.dumps(TAB_ID)});
      if (idx < 0) throw new Error("Gmail tab not found");
      return w.tabs()[idx].execute({{ javascript: {json.dumps(js)} }});
    }})()
    """
    res = subprocess.run(["osascript", "-l", "JavaScript", "-"], input=jxa, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip())
    return res.stdout.strip()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all inline images + attachment download URLs
    meta_raw = exec_js("""
    (() => {
      const items = [];
      const seen = new Set();

      // 1. Inline images in email body (.a3s img)
      const imgs = [...document.querySelectorAll(".a3s img")];
      let inlineIdx = 0;
      for (const img of imgs) {
        const src = img.src || "";
        if (!src || src.startsWith("data:") || seen.has(src)) continue;
        if (!src.includes("mail.google.com") && !src.includes("googleusercontent.com")) continue;
        seen.add(src);
        inlineIdx++;
        const alt = (img.alt || "").trim();
        const name = alt && alt.toLowerCase().includes("img_") ? alt : `inline_${String(inlineIdx).padStart(2, "0")}.jpeg`;
        items.push({ kind: "inline", name, url: src });
      }

      // 2. Attached files ([download_url])
      for (const el of document.querySelectorAll("[download_url]")) {
        const dl = el.getAttribute("download_url") || "";
        const parts = dl.split(":");
        if (parts.length >= 3) {
          const fname = parts[1];
          let url = parts.slice(2).join(":");
          // Fix Gmail's doubled prefix if present
          const secondHttp = url.indexOf("https://", 8);
          if (secondHttp > 0) url = url.slice(secondHttp);
          if (!seen.has(url)) {
            seen.add(url);
            items.push({ kind: "attachment", name: fname, url });
          }
        }
      }

      // Also capture exact filenames listed in body text
      const bodyTxt = [...document.querySelectorAll(".a3s")].map(e => e.innerText).join("\\n");
      return JSON.stringify({ items, bodyTxt });
    })()
    """)
    meta = json.loads(meta_raw)
    items = meta["items"]
    (OUT_DIR / "email_body.txt").write_text(meta["bodyTxt"], encoding="utf-8")
    print(f"Found {len(items)} release images in Vanessa's email:", flush=True)

    saved = []
    for i, it in enumerate(items, 1):
        fname = it["name"].replace("/", "_")
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            fname += ".jpeg"
        dst = OUT_DIR / fname
        if dst.exists() and dst.stat().st_size > 10_000:
            print(f"  [{i:02d}/{len(items)}] SKIP {fname}", flush=True)
            saved.append(fname)
            continue

        # Fetch via synchronous XHR as binary string inside authenticated Gmail tab
        b64 = exec_js(f"""
        (() => {{
          const xhr = new XMLHttpRequest();
          xhr.open("GET", {json.dumps(it["url"])}, false);
          xhr.withCredentials = true;
          xhr.overrideMimeType("text/plain; charset=x-user-defined");
          xhr.send();
          if (xhr.status !== 200) return "ERR_" + xhr.status;
          const raw = xhr.responseText;
          let bin = "";
          for (let k = 0; k < raw.length; k++) bin += String.fromCharCode(raw.charCodeAt(k) & 0xff);
          return btoa(bin);
        }})()
        """, timeout=120)

        if b64.startswith("ERR_") or len(b64) < 1000:
            print(f"  [{i:02d}/{len(items)}] FAIL {fname}: {b64[:80]}", flush=True)
            continue
        data = base64.b64decode(b64)
        dst.write_bytes(data)
        print(f"  [{i:02d}/{len(items)}] SAVED {fname} ({len(data)/1024:.1f} KB)", flush=True)
        saved.append(fname)

    print(f"\nSaved {len(saved)}/{len(items)} release images to {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
