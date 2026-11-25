/* PRECIPICE — Interactive Multi-Camera Dailies & Transcript Studio */
(() => {
  const CAM_ORDER = ["CHICARA_CAM", "ROB_CAM", "SECRET_CAM", "CHIKARA_BONUS"];

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

  // YouTube IFrame API hook
  window.onYouTubeIframeAPIReady = () => {
    state.ytApiReady = true;
    mountOrSwitchPlayer();
  };

  function getActiveVideoId() {
    return state.youtubeData?.[state.activeCam]?.video_id || "";
  }

  function mountOrSwitchPlayer(seekSec = null) {
    const vid = getActiveVideoId();
    const fb = $("#player-fallback");
    if (!vid) {
      fb.hidden = false;
      fb.innerHTML = "<p>YouTube video ID not yet linked for this camera.</p>";
      return;
    }
    fb.hidden = true;

    if (!state.ytApiReady || !window.YT || !window.YT.Player) {
      // Fallback plain iframe if YT API hasn't fired yet
      const container = $("#yt-player");
      if (container && container.tagName !== "IFRAME") {
        const startParam = seekSec != null ? `&start=${Math.floor(seekSec)}` : "";
        container.innerHTML = `<iframe src="https://www.youtube.com/embed/${vid}?rel=0&modestbranding=1${startParam}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
      }
      return;
    }

    if (!state.player) {
      state.player = new window.YT.Player("yt-player", {
        videoId: vid,
        playerVars: { rel: 0, modestbranding: 1, playsinline: 1 },
        events: {
          onReady: () => {
            if (seekSec != null) state.player.seekTo(seekSec, true);
            startSyncLoop();
          },
        },
      });
    } else if (typeof state.player.loadVideoById === "function") {
      const curId = state.player.getVideoData?.()?.video_id;
      if (curId !== vid) {
        state.player.loadVideoById({ videoId: vid, startSeconds: seekSec || 0 });
      } else if (seekSec != null) {
        state.player.seekTo(seekSec, true);
        state.player.playVideo?.();
      }
    }
  }

  function seekTo(camId, sec) {
    if (camId !== state.activeCam) {
      state.activeCam = camId;
      renderCameraBar();
      renderShotsGrid();
      mountOrSwitchPlayer(sec);
      renderInspector();
    } else {
      if (state.player && typeof state.player.seekTo === "function") {
        state.player.seekTo(sec, true);
        state.player.playVideo?.();
      } else {
        mountOrSwitchPlayer(sec);
      }
    }
    updateNowPlaying(sec);
  }

  function startSyncLoop() {
    clearInterval(state.syncTimer);
    state.syncTimer = setInterval(() => {
      if (!state.player || typeof state.player.getCurrentTime !== "function") return;
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
    if (activeRow && !state.searchQuery && state.inspectorMode === "transcript") {
      activeRow.scrollIntoView({ block: "nearest", behavior: "smooth" });
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

  function renderHightailAudio() {
    const ht = state.hightailData;
    if (!ht) return;
    $("#audio").hidden = false;

    const list = state.audioTab === "scene" ? (ht.scene_audio || []) : (ht.voice_refs || []);
    const q = state.audioQuery.trim().toLowerCase();
    const filtered = q
      ? list.filter((it) => (it.filename + " " + (it.text || "")).toLowerCase().includes(q))
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
          <span class="audio-title">${escHtml(it.filename)}</span>
          <span class="audio-badge">${escHtml(it.duration_hms)}</span>
        </div>
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

    // Lightbox controls
    $("#lightbox-close").addEventListener("click", () => { $("#lightbox").hidden = true; });
    $("#lightbox-prev").addEventListener("click", () => showLightboxAt(state.lightboxIdx - 1));
    $("#lightbox-next").addEventListener("click", () => showLightboxAt(state.lightboxIdx + 1));
    $("#lightbox").addEventListener("click", (e) => {
      if (e.target.id === "lightbox") $("#lightbox").hidden = true;
    });
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    $("#theme-icon-sun").style.display = theme === "dark" ? "" : "none";
    $("#theme-icon-moon").style.display = theme === "light" ? "" : "none";
  }

  async function boot() {
    wireUI();
    try {
      const [shotsRes, chapRes, ytRes, htRes] = await Promise.all([
        fetch("data/shots.json"),
        fetch("data/chapters.json").catch(() => null),
        fetch("data/youtube.json").catch(() => null),
        fetch("data/hightail_112326.json").catch(() => null),
      ]);
      state.shotsData = await shotsRes.json();
      if (chapRes && chapRes.ok) state.chaptersData = await chapRes.json();
      if (ytRes && ytRes.ok) state.youtubeData = await ytRes.json();
      if (htRes && htRes.ok) state.hightailData = await htRes.json();

      renderMetrics();
      renderCameraBar();
      renderShotsGrid();
      renderInspector();
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
