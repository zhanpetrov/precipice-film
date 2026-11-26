/* PRECIPICE — Interactive Multi-Camera Dailies & Transcript Studio */
(() => {
  const CAM_ORDER = ["CHICARA_CAM", "ROB_CAM", "SECRET_CAM", "ZHAN_CAM", "CHIKARA_BONUS", "DAY2_ROB_CAM", "DAY2_ZHAN_CAM"];

  const state = {
    shotsData: null,
    chaptersData: {},
    youtubeData: {},
    hightailData: null,
    activeCam: "CHICARA_CAM",
    activeShotIdx: 1,
    inspectorMode: "transcript",
    shotFilter: "all",
    searchQuery: "",
    audioTab: "voice",
    audioQuery: "",
    castStillsShown: 48,
    lightboxList: [],
    lightboxIdx: 0,
    player: null,
    ytApiReady: false,
    syncTimer: null,
  };

  const $ = (sel) => document.querySelector(sel);

  function fmtHMS(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function escHtml(str) {
    return (str || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  function highlight(text, q) {
    const safe = escHtml(text);
    if (!q) return safe;
    const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    return safe.replace(re, "<mark>$1</mark>");
  }

  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove("show"), 2200);
  }

  // Dynamically ensure YouTube IFrame API is loaded with zero race conditions
  function ensureYTApi() {
    if (window.YT && window.YT.Player) {
      state.ytApiReady = true;
      return;
    }
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (typeof prev === "function") prev();
      state.ytApiReady = true;
      mountOrSwitchPlayer(state.pendingSeek);
    };
    if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
      const tag = document.createElement("script");
      tag.src = "https://www.youtube.com/iframe_api";
      tag.async = true;
      document.head.appendChild(tag);
    }
  }

  function getActiveVideoId() {
    return state.youtubeData?.[state.activeCam]?.video_id || "";
  }

  function mountOrSwitchPlayer(seekSec = null, autoplay = false) {
    const vid = getActiveVideoId();
    const fb = $("#player-fallback");
    if (!vid) {
      if (fb) {
        fb.hidden = false;
        fb.innerHTML = "<p>Loading camera stream…</p>";
      }
      return;
    }
    if (fb) fb.hidden = true;

    // Check if YT API is already ready
    if (window.YT && window.YT.Player) {
      state.ytApiReady = true;
    }

    if (!state.ytApiReady) {
      state.pendingSeek = seekSec;
      state.pendingAutoplay = autoplay;
      ensureYTApi();
      return;
    }

    if (!state.player) {
      // Ensure clean mount node before creating YT.Player
      const shell = $(".player-aspect");
      let mount = $("#yt-player");
      if (!mount || mount.tagName === "IFRAME") {
        if (mount) mount.remove();
        mount = document.createElement("div");
        mount.id = "yt-player";
        shell.prepend(mount);
      } else {
        mount.innerHTML = "";
      }

      const playerVars = {
        rel: 0,
        modestbranding: 1,
        playsinline: 1,
        enablejsapi: 1,
        fs: 1,
      };
      if (location.protocol.startsWith("http")) {
        playerVars.origin = location.origin;
        playerVars.widget_referrer = location.href;
      }

      state.playerReady = false;
      state.pendingSeek = seekSec;
      state.pendingAutoplay = autoplay;

      state.player = new window.YT.Player("yt-player", {
        width: "100%",
        height: "100%",
        videoId: vid,
        playerVars,
        events: {
          onReady: (ev) => {
            state.playerReady = true;
            try {
              const ifr = ev.target.getIframe();
              if (ifr) {
                ifr.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
                ifr.setAttribute("allow", "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share");
                ifr.setAttribute("allowfullscreen", "");
              }
            } catch (_) {}

            const targetVid = getActiveVideoId();
            const curVid = ev.target.getVideoData?.()?.video_id;
            const startAt = state.pendingSeek != null ? state.pendingSeek : 0;
            const shouldPlay = !!state.pendingAutoplay;
            state.pendingSeek = null;
            state.pendingAutoplay = false;

            if (targetVid && curVid && curVid !== targetVid) {
              if (shouldPlay) ev.target.loadVideoById({ videoId: targetVid, startSeconds: startAt });
              else ev.target.cueVideoById({ videoId: targetVid, startSeconds: startAt });
            } else if (startAt > 0) {
              ev.target.seekTo(startAt, true);
              if (shouldPlay) ev.target.playVideo?.();
            }
            startSyncLoop();
          },
          onError: (ev) => {
            console.warn("YouTube Player error:", ev.data);
            if (fb) {
              fb.hidden = false;
              fb.innerHTML = `<div style="text-align:center;padding:20px"><p style="margin:0 0 12px">YouTube embed unavailable (code ${ev.data}).</p><a class="pill-btn primary" href="https://www.youtube.com/watch?v=${vid}&list=PLcER0Yz7OUpU" target="_blank" rel="noopener">Open Video on YouTube ↗</a></div>`;
            }
          },
        },
      });
      return;
    }

    if (!state.playerReady) {
      state.pendingSeek = seekSec;
      state.pendingAutoplay = autoplay;
      return;
    }

    const curId = state.player.getVideoData?.()?.video_id;
    const startAt = seekSec != null ? seekSec : 0;
    if (curId !== vid) {
      if (autoplay) state.player.loadVideoById({ videoId: vid, startSeconds: startAt });
      else state.player.cueVideoById({ videoId: vid, startSeconds: startAt });
    } else if (seekSec != null) {
      state.player.seekTo(startAt, true);
      if (autoplay) state.player.playVideo?.();
    }
  }

  function seekTo(camId, sec) {
    if (camId !== state.activeCam) {
      state.activeCam = camId;
      state.lastActiveRow = null;
      renderCameraBar();
      renderShotsGrid();
      mountOrSwitchPlayer(sec, true);
      renderInspector();
    } else {
      mountOrSwitchPlayer(sec, true);
    }
    updateNowPlaying(sec);
  }

  function startSyncLoop() {
    clearInterval(state.syncTimer);
    state.syncTimer = setInterval(() => {
      if (!state.player || !state.playerReady || typeof state.player.getCurrentTime !== "function") return;
      const t = state.player.getCurrentTime();
      if (Number.isFinite(t)) updateNowPlaying(t);
    }, 600);
  }

  function findShotAtTime(camObj, t) {
    const shots = camObj.shots || [];
    let current = shots[0] || null;
    for (const s of shots) {
      const off = s.master_offset ?? s.camera_offset ?? 0;
      if (t >= off - 0.25) current = s;
      else break;
    }
    return current;
  }

  function updateNowPlaying(t) {
    const camObj = state.shotsData?.cameras?.[state.activeCam];
    if (!camObj) return;
    $("#np-timecode").textContent = fmtHMS(t);
    const shot = findShotAtTime(camObj, t);
    if (!shot) return;

    const changed = state.activeShotIdx !== shot.shot_index;
    state.activeShotIdx = shot.shot_index;

    $("#np-badge").textContent = `SHOT ${String(shot.shot_index).padStart(2, "0")}`;
    $("#np-title").textContent = `${shot.filename} — ${shot.text ? shot.text.slice(0, 72) + (shot.text.length > 72 ? "…" : "") : "Ambient / Camera Roll"}`;
    const created = shot.creation_time ? shot.creation_time.replace("T", " ").slice(0, 19) : "";
    $("#np-sub").textContent = `${camObj.label} · ${fmtHMS(shot.master_duration ?? shot.duration)} · ${shot.display_width}×${shot.display_height} · ${shot.word_count} words${created ? " · " + created : ""}`;

    if (changed) {
      document.querySelectorAll(".shot-card").forEach((el) => {
        el.classList.toggle("active", Number(el.dataset.shot) === shot.shot_index);
      });
      if (state.inspectorMode === "shot" && !state.searchQuery) {
        renderInspector();
      }
    }

    // Highlight active transcript line
    const rows = document.querySelectorAll("#inspector-body .t-row[data-start]");
    let activeRow = null;
    rows.forEach((r) => {
      const s = parseFloat(r.dataset.start);
      const e = parseFloat(r.dataset.end);
      const isHit = t >= s && t <= e + 0.4;
      r.classList.toggle("active", isHit);
      if (isHit) activeRow = r;
    });
    if (activeRow && activeRow !== state.lastActiveRow && !state.searchQuery && state.inspectorMode === "transcript") {
      state.lastActiveRow = activeRow;
      const isPlaying = state.player && typeof state.player.getPlayerState === "function" && state.player.getPlayerState() === 1;
      if (isPlaying) {
        const container = $("#inspector-body");
        if (container) {
          const targetTop = activeRow.offsetTop - container.offsetTop - container.clientHeight * 0.35;
          container.scrollTo({ top: Math.max(0, targetTop), behavior: "smooth" });
        }
      }
    }
  }

  function renderMetrics() {
    const cams = state.shotsData.cameras;
    let totalShots = 0;
    let totalDur = 0;
    let totalWords = 0;
    for (const id of CAM_ORDER) {
      const c = cams[id];
      if (!c) continue;
      totalShots += c.shot_count || 0;
      totalDur += c.master_duration || c.total_duration || 0;
      totalWords += c.total_words || 0;
    }
    $("#stat-cameras").textContent = String(CAM_ORDER.filter((id) => cams[id]).length);
    $("#stat-shots").textContent = String(totalShots);
    $("#stat-runtime").textContent = fmtHMS(totalDur);
    $("#stat-words").textContent = totalWords.toLocaleString();
  }

  function renderCameraBar() {
    const sw = $("#camera-switcher");
    sw.innerHTML = "";
    for (const id of CAM_ORDER) {
      const c = state.shotsData.cameras[id];
      if (!c) continue;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "seg-btn" + (id === state.activeCam ? " active" : "");
      btn.innerHTML = `<span>${escHtml(c.label)}</span><span class="seg-meta">${c.shot_count} · ${fmtHMS(c.master_duration || c.total_duration)}</span>`;
      btn.addEventListener("click", () => {
        if (state.activeCam === id) return;
        state.activeCam = id;
        state.activeShotIdx = 1;
        renderCameraBar();
        renderShotsGrid();
        mountOrSwitchPlayer(0);
        renderInspector();
        updateNowPlaying(0);
      });
      sw.appendChild(btn);
    }

    const active = state.shotsData.cameras[state.activeCam];
    const yt = state.youtubeData[state.activeCam];
    $("#btn-yt-watch").href = yt?.playlist_watch_url || yt?.watch_url || "#";
    $("#btn-dl-txt").href = active.full_transcript_txt;
    $("#btn-dl-srt").href = active.full_transcript_srt;
  }

  function renderInspector() {
    const body = $("#inspector-body");
    const q = state.searchQuery.trim();
    const countEl = $("#search-count");

    // Global cross-camera search mode
    if (q.length >= 2) {
      const ql = q.toLowerCase();
      const hits = [];
      for (const camId of CAM_ORDER) {
        const c = state.shotsData.cameras[camId];
        if (!c) continue;
        for (const s of c.shots) {
          const baseOff = s.master_offset ?? s.camera_offset ?? 0;
          for (const seg of s.segments || []) {
            if ((seg.text || "").toLowerCase().includes(ql)) {
              hits.push({
                camId,
                camLabel: c.label,
                shotIdx: s.shot_index,
                filename: s.filename,
                start: baseOff + seg.start,
                end: baseOff + seg.end,
                text: seg.text,
              });
            }
          }
        }
      }
      countEl.hidden = false;
      countEl.textContent = String(hits.length);
      if (!hits.length) {
        body.innerHTML = `<div class="empty-state">No dialogue matches "${escHtml(q)}" across any camera.</div>`;
        return;
      }
      body.innerHTML = hits.slice(0, 250).map((h) => `
        <div class="t-row" data-cam="${h.camId}" data-seek="${h.start}">
          <span class="t-ts">${fmtHMS(h.start)}</span>
          <div class="t-content">
            <span class="t-shot-tag">${escHtml(h.camLabel)} · Shot ${String(h.shotIdx).padStart(2, "0")} (${escHtml(h.filename)})</span>
            <div class="t-text">${highlight(h.text, q)}</div>
          </div>
        </div>
      `).join("");
      body.querySelectorAll(".t-row").forEach((el) => {
        el.addEventListener("click", () => seekTo(el.dataset.cam, parseFloat(el.dataset.seek)));
      });
      return;
    }

    countEl.hidden = true;
    const camObj = state.shotsData.cameras[state.activeCam];

    if (state.inspectorMode === "chapters") {
      const chs = state.chaptersData[state.activeCam] || [];
      if (!chs.length) {
        body.innerHTML = `<div class="empty-state">No chapters available.</div>`;
        return;
      }
      body.innerHTML = chs.map((ch) => `
        <div class="t-row" data-seek="${ch.time}">
          <span class="t-ts">${escHtml(ch.ts)}</span>
          <div class="t-content">
            <div class="t-text">${escHtml(ch.title)}</div>
          </div>
        </div>
      `).join("");
      body.querySelectorAll(".t-row").forEach((el) => {
        el.addEventListener("click", () => seekTo(state.activeCam, parseFloat(el.dataset.seek)));
      });
      return;
    }

    const shotsToShow = state.inspectorMode === "shot"
      ? camObj.shots.filter((s) => s.shot_index === state.activeShotIdx)
      : camObj.shots;

    const parts = [];
    for (const s of shotsToShow) {
      const baseOff = s.master_offset ?? s.camera_offset ?? 0;
      if (!s.segments || !s.segments.length) {
        parts.push(`
          <div class="t-row" data-start="${baseOff}" data-end="${baseOff + s.duration}" data-seek="${baseOff}">
            <span class="t-ts">${fmtHMS(baseOff)}</span>
            <div class="t-content">
              <span class="t-shot-tag">Shot ${String(s.shot_index).padStart(2, "0")} · ${escHtml(s.filename)}</span>
              <div class="t-text" style="color:var(--text-tertiary)">Ambient / non-dialogue roll (${fmtHMS(s.duration)})</div>
            </div>
          </div>
        `);
        continue;
      }
      for (let i = 0; i < s.segments.length; i++) {
        const seg = s.segments[i];
        const gs = baseOff + seg.start;
        const ge = baseOff + seg.end;
        const tag = i === 0 ? `<span class="t-shot-tag">Shot ${String(s.shot_index).padStart(2, "0")} · ${escHtml(s.filename)}</span>` : "";
        parts.push(`
          <div class="t-row" data-start="${gs}" data-end="${ge}" data-seek="${gs}">
            <span class="t-ts">${fmtHMS(gs)}</span>
            <div class="t-content">
              ${tag}
              <div class="t-text">${escHtml(seg.text)}</div>
            </div>
          </div>
        `);
      }
    }

    body.innerHTML = parts.length ? parts.join("") : `<div class="empty-state">No transcript lines found.</div>`;
    body.querySelectorAll(".t-row").forEach((el) => {
      el.addEventListener("click", () => seekTo(state.activeCam, parseFloat(el.dataset.seek)));
    });
  }

  function renderShotsGrid() {
    const camObj = state.shotsData.cameras[state.activeCam];
    $("#shots-heading").textContent = `${camObj.label} — ${camObj.shot_count} ${camObj.shot_count === 1 ? "Shot" : "Shots"}`;
    const list = state.shotFilter === "dialogue"
      ? camObj.shots.filter((s) => (s.word_count || 0) > 0)
      : camObj.shots;

    const grid = $("#shots-grid");
    grid.innerHTML = list.map((s) => {
      const off = s.master_offset ?? s.camera_offset ?? 0;
      const dur = s.master_duration ?? s.duration ?? 0;
      const active = s.shot_index === state.activeShotIdx ? " active" : "";
      const snippet = s.text ? escHtml(s.text) : "Ambient / camera roll (no spoken dialogue detected)";
      return `
        <article class="shot-card${active}" data-shot="${s.shot_index}" data-seek="${off}">
          <div class="shot-thumb-wrap">
            <img src="${escHtml(s.thumb)}" alt="${escHtml(s.filename)}" loading="lazy" />
            <span class="shot-ts-pill">${fmtHMS(off)}</span>
            <span class="shot-dur-pill">${fmtHMS(dur)}</span>
          </div>
          <div class="shot-body">
            <div class="shot-top">
              <span class="shot-name">#${String(s.shot_index).padStart(2, "0")} · ${escHtml(s.filename)}</span>
              <span class="shot-words">${s.word_count}w</span>
            </div>
            <div class="shot-snippet">${snippet}</div>
          </div>
        </article>
      `;
    }).join("");

    grid.querySelectorAll(".shot-card").forEach((card) => {
      card.addEventListener("click", () => {
        const sec = parseFloat(card.dataset.seek);
        seekTo(state.activeCam, sec);
        $("#studio").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function openLightbox(list, idx) {
    state.lightboxList = list;
    state.lightboxIdx = idx;
    showLightboxAt(idx);
    $("#lightbox").hidden = false;
  }

  function showLightboxAt(idx) {
    const list = state.lightboxList;
    if (!list.length) return;
    state.lightboxIdx = (idx + list.length) % list.length;
    const item = list[state.lightboxIdx];
    $("#lightbox-img").src = item.src;
    $("#lightbox-caption").textContent = `${item.cap} (${state.lightboxIdx + 1} / ${list.length})`;
  }

  function renderPeople() {
    const cp = state.castPeopleData;
    const people = cp?.people || [];
    if (!people.length) return;
    $("#people").hidden = false;
    $("#people-title").textContent = `People & Cast (${people.length} Recognized)`;

    const q = (state.peopleQuery || "").trim().toLowerCase();
    const filtered = q
      ? people.filter((p) => (p.name + " " + p.id + " " + (p.voice_sample?.role || "")).toLowerCase().includes(q))
      : people;

    const grid = $("#people-grid");
    if (!filtered.length) {
      grid.innerHTML = `<div class="empty-state">No people match "${escHtml(state.peopleQuery)}".</div>`;
      return;
    }

    grid.innerHTML = filtered.map((p) => `
      <article class="person-card${p.verified_identity ? " verified" : ""}" data-pid="${escHtml(p.id)}">
        <div class="person-avatar-wrap">
          <img class="person-avatar" src="${escHtml(p.avatar)}" alt="${escHtml(p.name)}" loading="lazy" />
          ${p.voice_sample ? `<span class="person-voice-dot" title="Voice sample linked">♪</span>` : ""}
        </div>
        <div class="person-name">${escHtml(p.name)}</div>
        <div class="person-meta">${p.photo_count} ${p.photo_count === 1 ? "photo" : "photos"}</div>
        ${p.release_signed ? `<div class="person-signed-badge">✓ Signed Release</div>` : ""}
      </article>
    `).join("");

    grid.querySelectorAll(".person-card").forEach((card) => {
      card.addEventListener("click", () => {
        const person = people.find((x) => x.id === card.dataset.pid);
        if (person) openPersonModal(person);
      });
    });
  }

  function openPersonModal(person) {
    $("#pm-avatar").src = person.avatar;
    $("#pm-avatar").alt = person.name;
    $("#pm-name").textContent = person.name;
    const relTag = person.release_signed ? ` · ✓ Signed Release (${person.release_date || "11/23/26"})` : "";
    $("#pm-meta").textContent = `${person.photo_count} matched portraits${relTag}`;

    const voiceBox = $("#pm-voice");
    const blocks = [];
    if (person.release_img) {
      blocks.push(`
        <div class="audio-card-head">
          <span class="signed-pill">✓ Signed Photo &amp; Video Release</span>
          <button id="pm-open-release" class="mini-btn" type="button">View Signed Release</button>
        </div>
      `);
    }
    if (person.voice_sample) {
      const v = person.voice_sample;
      blocks.push(`
        <div class="audio-card-head">
          <span class="audio-title">Voice Sample · ${escHtml(v.role || "Cast")}</span>
          <span class="audio-badge">${escHtml(v.duration_hms)}</span>
        </div>
        <audio controls preload="metadata" src="${escHtml(v.audio)}"></audio>
        <div class="pm-voice-text">${escHtml(v.text || "")}</div>
      `);
    }
    if (blocks.length) {
      voiceBox.hidden = false;
      voiceBox.innerHTML = blocks.join("");
      $("#pm-open-release")?.addEventListener("click", () => {
        openLightbox([{ src: person.release_img, cap: `${person.name} — Signed Release (${person.release_date || "2026-11-23"})` }], 0);
      });
    } else {
      voiceBox.hidden = true;
      voiceBox.innerHTML = "";
    }

    const lbList = person.stills.map((s) => ({ src: s.full, cap: `${person.name} · ${s.filename}` }));
    const photosEl = $("#pm-photos");
    photosEl.innerHTML = person.stills.map((s, idx) => `
      <div class="pm-photo-tile" data-idx="${idx}">
        <img src="${escHtml(s.thumb)}" alt="${escHtml(s.filename)}" loading="lazy" />
      </div>
    `).join("");

    photosEl.querySelectorAll(".pm-photo-tile").forEach((el) => {
      el.addEventListener("click", () => openLightbox(lbList, Number(el.dataset.idx)));
    });

    $("#person-modal").hidden = false;
  }

  function renderReleases() {
    const rd = state.releasesData;
    const list = rd?.releases || [];
    if (!list.length) return;
    $("#releases").hidden = false;
    $("#releases-title").textContent = `Signed Actor Releases (${list.length} Signed · ${rd.scans_archived} Scans)`;

    const q = (state.releasesQuery || "").trim().toLowerCase();
    const filtered = q
      ? list.filter((r) => (r.legal_name + " " + (r.role || "") + " " + r.source_file).toLowerCase().includes(q))
      : list;

    const grid = $("#releases-grid");
    if (!filtered.length) {
      grid.innerHTML = `<div class="empty-state">No signed actors match "${escHtml(state.releasesQuery)}".</div>`;
      return;
    }

    const people = state.castPeopleData?.people || [];
    grid.innerHTML = filtered.map((r) => {
      const initials = r.legal_name.split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();
      const avatarHtml = r.avatar
        ? `<img class="rel-avatar" src="${escHtml(r.avatar)}" alt="${escHtml(r.legal_name)}" loading="lazy" />`
        : `<span class="rel-avatar">${escHtml(initials)}</span>`;
      const scanBtn = r.release_img
        ? `<button class="mini-btn rel-view-scan" data-img="${escHtml(r.release_img)}" data-cap="${escHtml(r.legal_name)} — Signed Release (${escHtml(r.date_signed)})" type="button">View Release</button>`
        : `<span class="shot-words">Signed · Scan pending Drive share (${escHtml(r.source_file)})</span>`;
      const photosBtn = r.person_id
        ? `<button class="mini-btn rel-open-person" data-pid="${escHtml(r.person_id)}" type="button">${r.photo_count} Portraits</button>`
        : "";
      const audioHtml = r.voice_audio
        ? `<audio controls preload="none" src="${escHtml(r.voice_audio)}"></audio>`
        : "";
      return `
        <article class="release-card">
          <div class="rel-top">
            ${avatarHtml}
            <div class="rel-info">
              <div class="rel-name">${escHtml(r.legal_name)}</div>
              <div class="rel-sub">${escHtml(r.role || "Cast")} · Signed ${escHtml(r.date_signed)}</div>
            </div>
            <span class="signed-pill">✓ Signed</span>
          </div>
          <div class="rel-actions">
            ${scanBtn}
            ${photosBtn}
          </div>
          ${audioHtml}
        </article>
      `;
    }).join("");

    grid.querySelectorAll(".rel-view-scan").forEach((btn) => {
      btn.addEventListener("click", () => {
        openLightbox([{ src: btn.dataset.img, cap: btn.dataset.cap }], 0);
      });
    });
    grid.querySelectorAll(".rel-open-person").forEach((btn) => {
      btn.addEventListener("click", () => {
        const p = people.find((x) => x.id === btn.dataset.pid);
        if (p) openPersonModal(p);
      });
    });
  }

  function renderHightailAudio() {
    const ht = state.hightailData;
    if (!ht) return;
    $("#audio").hidden = false;

    const list = state.audioTab === "scene" ? (ht.scene_audio || []) : (ht.voice_refs || []);
    const q = state.audioQuery.trim().toLowerCase();
    const filtered = q
      ? list.filter((it) => ((it.speaker || "") + " " + (it.role || "") + " " + it.filename + " " + (it.text || "")).toLowerCase().includes(q))
      : list;

    $("#audio-count").textContent = `${filtered.length} of ${list.length} recordings`;
    const grid = $("#audio-grid");
    if (!filtered.length) {
      grid.innerHTML = `<div class="empty-state">No recordings match "${escHtml(state.audioQuery)}".</div>`;
      return;
    }

    grid.innerHTML = filtered.map((it) => `
      <article class="audio-card">
        <div class="audio-card-head">
          <span class="audio-title">${escHtml(it.speaker || it.filename)}</span>
          <span class="audio-badge">${escHtml(it.duration_hms)}</span>
        </div>
        ${it.role ? `<div class="audio-role">${escHtml(it.role)} · ${escHtml(it.id)}</div>` : ""}
        <audio controls preload="none" src="${escHtml(it.audio)}"></audio>
        <div class="audio-transcript">${it.text ? highlight(it.text, state.audioQuery.trim()) : "<em>Ambient / no speech detected</em>"}</div>
      </article>
    `).join("");
  }

  function renderCastStills() {
    const ht = state.hightailData;
    const stills = ht?.cast_stills || [];
    if (!stills.length) return;
    $("#cast-stills").hidden = false;
    $("#cast-stills-title").textContent = `Cast Stills Gallery (${stills.length} Photos)`;

    const slice = stills.slice(0, state.castStillsShown);
    const lbList = stills.map((s) => ({ src: s.full, cap: s.filename }));

    const grid = $("#cast-stills-grid");
    grid.innerHTML = slice.map((s, idx) => `
      <figure class="cast-still-tile" data-idx="${idx}">
        <img src="${escHtml(s.thumb)}" alt="${escHtml(s.filename)}" loading="lazy" />
        <figcaption class="cast-still-label">${escHtml(s.filename)}</figcaption>
      </figure>
    `).join("");

    grid.querySelectorAll(".cast-still-tile").forEach((el) => {
      el.addEventListener("click", () => openLightbox(lbList, Number(el.dataset.idx)));
    });

    const moreWrap = $("#cast-stills-more");
    if (state.castStillsShown < stills.length) {
      moreWrap.hidden = false;
      $("#btn-load-more-stills").textContent = `Load 60 More (${stills.length - state.castStillsShown} left)`;
    } else {
      moreWrap.hidden = true;
    }
  }

  function renderStills() {
    const stills = state.shotsData.stills || [];
    if (!stills.length) return;
    $("#stills").hidden = false;
    const lbList = stills.map((s) => ({ src: s.path, cap: s.filename }));
    const grid = $("#stills-grid");
    grid.innerHTML = stills.map((st, idx) => `
      <figure class="still-card" data-idx="${idx}">
        <img src="${escHtml(st.path)}" alt="${escHtml(st.filename)}" loading="lazy" />
        <figcaption class="still-cap">${escHtml(st.filename)}</figcaption>
      </figure>
    `).join("");

    grid.querySelectorAll(".still-card").forEach((el) => {
      el.addEventListener("click", () => openLightbox(lbList, Number(el.dataset.idx)));
    });
  }

  function wireUI() {
    // Theme toggle
    const savedTheme = localStorage.getItem("precipice_theme") || "dark";
    applyTheme(savedTheme);
    $("#theme-toggle").addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
      localStorage.setItem("precipice_theme", next);
    });

    // Search
    const searchInput = $("#transcript-search");
    searchInput.addEventListener("input", () => {
      state.searchQuery = searchInput.value;
      renderInspector();
    });
    $("#search-trigger").addEventListener("click", () => {
      $("#studio").scrollIntoView({ behavior: "smooth" });
      setTimeout(() => searchInput.focus(), 200);
    });
    window.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInput.focus();
      } else if (!$("#lightbox").hidden) {
        if (e.key === "Escape") $("#lightbox").hidden = true;
        else if (e.key === "ArrowLeft") showLightboxAt(state.lightboxIdx - 1);
        else if (e.key === "ArrowRight") showLightboxAt(state.lightboxIdx + 1);
      } else if (!$("#person-modal").hidden && e.key === "Escape") {
        $("#person-modal").hidden = true;
      }
    });

    // Inspector tabs
    document.querySelectorAll(".itab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".itab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        state.inspectorMode = tab.dataset.mode;
        renderInspector();
      });
    });

    // Shot filters
    document.querySelectorAll(".filter-pill[data-filter]").forEach((pill) => {
      pill.addEventListener("click", () => {
        document.querySelectorAll(".filter-pill[data-filter]").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        state.shotFilter = pill.dataset.filter;
        renderShotsGrid();
      });
    });

    // People & Releases search + modal close
    $("#people-search")?.addEventListener("input", (e) => {
      state.peopleQuery = e.target.value;
      renderPeople();
    });
    $("#releases-search")?.addEventListener("input", (e) => {
      state.releasesQuery = e.target.value;
      renderReleases();
    });
    $("#pm-close")?.addEventListener("click", () => { $("#person-modal").hidden = true; });
    $("#person-modal")?.addEventListener("click", (e) => {
      if (e.target.id === "person-modal") $("#person-modal").hidden = true;
    });

    // Audio Studio tabs & search
    document.querySelectorAll(".audio-tab[data-atab]").forEach((pill) => {
      pill.addEventListener("click", () => {
        document.querySelectorAll(".audio-tab[data-atab]").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        state.audioTab = pill.dataset.atab;
        renderHightailAudio();
      });
    });
    $("#audio-search")?.addEventListener("input", (e) => {
      state.audioQuery = e.target.value;
      renderHightailAudio();
    });

    // Cast stills pagination
    $("#btn-load-more-stills")?.addEventListener("click", () => {
      state.castStillsShown += 60;
      renderCastStills();
    });
    $("#btn-show-all-stills")?.addEventListener("click", () => {
      state.castStillsShown = 9999;
      renderCastStills();
    });

    // Copy timestamped YouTube link
    $("#btn-copy-link").addEventListener("click", () => {
      const vid = getActiveVideoId();
      const t = Math.floor(state.player?.getCurrentTime?.() || 0);
      const url = vid ? `https://youtu.be/${vid}?t=${t}` : location.href;
      navigator.clipboard?.writeText(url).then(() => toast(`Copied ${url}`));
    });

    // Lightbox controls + phone touch swipe gestures
    const lb = $("#lightbox");
    $("#lightbox-close").addEventListener("click", () => { lb.hidden = true; });
    $("#lightbox-prev").addEventListener("click", () => showLightboxAt(state.lightboxIdx - 1));
    $("#lightbox-next").addEventListener("click", () => showLightboxAt(state.lightboxIdx + 1));
    lb.addEventListener("click", (e) => {
      if (e.target.id === "lightbox") lb.hidden = true;
    });
    let touchStartX = 0;
    lb.addEventListener("touchstart", (e) => {
      if (e.touches.length === 1) touchStartX = e.touches[0].clientX;
    }, { passive: true });
    lb.addEventListener("touchend", (e) => {
      if (!touchStartX || !e.changedTouches.length) return;
      const dx = e.changedTouches[0].clientX - touchStartX;
      touchStartX = 0;
      if (Math.abs(dx) > 45) {
        if (dx < 0) showLightboxAt(state.lightboxIdx + 1);
        else showLightboxAt(state.lightboxIdx - 1);
      }
    }, { passive: true });
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    $("#theme-icon-sun").style.display = theme === "dark" ? "" : "none";
    $("#theme-icon-moon").style.display = theme === "light" ? "" : "none";
  }

  async function boot() {
    wireUI();
    try {
      const [shotsRes, chapRes, ytRes, htRes, cpRes, relRes] = await Promise.all([
        fetch("data/shots.json"),
        fetch("data/chapters.json").catch(() => null),
        fetch("data/youtube.json").catch(() => null),
        fetch("data/hightail_112326.json").catch(() => null),
        fetch("data/cast_people.json").catch(() => null),
        fetch("data/releases.json").catch(() => null),
      ]);
      state.shotsData = await shotsRes.json();
      if (chapRes && chapRes.ok) state.chaptersData = await chapRes.json();
      if (ytRes && ytRes.ok) state.youtubeData = await ytRes.json();
      if (htRes && htRes.ok) state.hightailData = await htRes.json();
      if (cpRes && cpRes.ok) state.castPeopleData = await cpRes.json();
      if (relRes && relRes.ok) state.releasesData = await relRes.json();

      renderMetrics();
      renderCameraBar();
      renderShotsGrid();
      renderInspector();
      renderPeople();
      renderReleases();
      renderHightailAudio();
      renderCastStills();
      renderStills();
      mountOrSwitchPlayer();
      updateNowPlaying(0);
    } catch (err) {
      console.error(err);
      $("#inspector-body").innerHTML = `<div class="empty-state">Could not load archive data.</div>`;
    }
  }

  boot();
})();
