"use strict";

/* ===========================================================================
   Watermark Studio -- the 3-D model of the scheme

   64 block towers on three planes, flat-shaded, painter's algorithm, canvas
   2-D. No three.js, no WebGL, no CDN <script>. The reasons, in order:

     - the sidebar promises "runs entirely on this machine, no data leaves it",
       and a CDN tag quietly breaks that promise on every page load. Vendoring
       600 kB of library to draw 192 axis-aligned boxes is the other bad option.
     - every colour below is a CSS custom property read at run time, so the
       model re-themes with the rest of the app. A model shipping its own
       palette drifts out of sync with the design tokens within one commit.
     - flat-shaded boxes under a fixed-elevation camera need exactly two
       classical tricks -- depth sort and back-face cull -- and nothing else.

   What it shows is the actual scheme, not decoration: the block-to-partner
   map is a fixed coprime stride like the real one, the tampered set is a pen
   stroke across the grid, and a block is magenta only when it AND its partner
   were both hit. That last case is the coincidence limit the Attack lab
   demonstrates, and here you can watch it happen.
   =========================================================================== */

(function () {
  const canvas = document.getElementById("scheme3d");
  if (!canvas) return;                       // model is optional; app works without it
  const ctx = canvas.getContext("2d");
  const capEl = document.getElementById("scheme3d-cap");
  const GRID = 8;
  const N = GRID * GRID;

  /* --- theme -------------------------------------------------------------
     Custom properties cannot be read directly: getPropertyValue("--accent")
     hands back the literal text "var(--indigo-600)", unresolved. Assigning the
     var() to a real property on a probe element and reading the computed value
     back forces the cascade to resolve it, always as "rgb(r, g, b)". */
  const TOKENS = ["--surface", "--surface-3", "--border-strong", "--text-muted",
                  "--accent", "--accent-hover", "--accent-soft", "--bad", "--ok"];
  let theme = null;

  function readTheme() {
    const probe = document.createElement("div");
    probe.style.cssText = "position:absolute;left:-9999px;width:0;height:0";
    document.body.appendChild(probe);
    const out = {};
    for (const t of TOKENS) {
      probe.style.color = `var(${t})`;
      const m = getComputedStyle(probe).color.match(/[\d.]+/g);
      out[t] = m ? [+m[0], +m[1], +m[2]] : [128, 128, 128];
    }
    probe.remove();
    // Same constant as paint_unrecoverable() in src/recover.py. Hard-coded on
    // purpose: it is a signal, not a theme colour, and must read identically
    // in light and dark so the model and the repaired PNG agree.
    out.unrec = [213, 0, 249];
    // An intact block cannot be --surface: a white box on a near-white stage
    // renders as nothing but its own grey side faces, which reads as wireframe.
    // Pulling the surface toward the muted text tone lands a mid-grey that has
    // real contrast against the stage in BOTH themes -- lighter than the dark
    // background, darker than the light one -- without inventing a new token.
    out.block = mixc(out["--surface-3"], out["--text-muted"], 0.72);
    out.fixed = mixc(out.block, out["--accent"], 0.5);
    return out;
  }
  const dropTheme = () => { theme = null; };
  new MutationObserver(dropTheme).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-theme"] });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", dropTheme);

  const lerp = (a, b, t) => a + (b - a) * t;
  const mixc = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
  const shade = (c, f) => `rgb(${c[0] * f | 0},${c[1] * f | 0},${c[2] * f | 0})`;
  const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
  const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
  const ease = (u) => (u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2);

  /* --- the scheme, in miniature ----------------------------------------- */

  // Deterministic jitter. A seeded LCG rather than Math.random so two
  // screenshots of the same timestamp are identical -- the UI test suite
  // compares rendered pages, and a random scatter would make it flap.
  const rnd = (() => {
    let s = 20260812;
    return () => (s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  })();
  const JITTER = Array.from({ length: N }, () => [rnd() - 0.5, rnd() - 0.5, rnd() - 0.5]);

  // The pen stroke: one long diagonal plus a shorter return sweep, because a
  // real scribble doubles back and that is what produces the coincidence case.
  const TAMPERED = new Array(N).fill(false);
  for (let i = 0; i < GRID; i++) {
    for (let j = 0; j < GRID; j++) {
      const onMain = Math.abs(j - i) < 1.1;
      const onBack = Math.abs(j - (GRID - 1 - i) * 0.62 - 1.4) < 0.75;
      if (onMain || onBack) TAMPERED[i * GRID + j] = true;
    }
  }
  // Fixed coprime stride, the same shape of map src/ uses: a block's backup
  // always lands far from the block itself, so local damage cannot take both.
  const PARTNER = Array.from({ length: N }, (_, k) => (k * 37 + 11) % N);
  // Unrecoverable == flagged AND its partner flagged. Guarantee the model shows
  // at least one, since that limit is the honest half of what it is explaining.
  if (!TAMPERED.some((t, k) => t && TAMPERED[PARTNER[k]])) {
    TAMPERED[PARTNER[TAMPERED.indexOf(true)]] = true;
  }
  const UNREC = TAMPERED.map((t, k) => t && TAMPERED[PARTNER[k]]);
  // Reverse map: for an intact block, which flagged block is it about to donate
  // its backup to? Built once -- searching PARTNER per block per frame is 4096
  // scans a frame for an answer that never changes.
  const DONOR_OF = new Array(N).fill(-1);
  TAMPERED.forEach((t, k) => {
    if (t && !UNREC[k]) DONOR_OF[PARTNER[k]] = k;
  });
  const FLAGGED = TAMPERED.reduce((a, t) => a + (t ? 1 : 0), 0);
  const LOST = UNREC.reduce((a, t) => a + (t ? 1 : 0), 0);

  // Diagonal wave order, so every staggered animation sweeps the grid the same
  // way the camera reads it instead of jumping about in index order.
  const ORDER = Array.from({ length: N }, (_, k) => k)
    .sort((a, b) => ((a / GRID | 0) + a % GRID) - ((b / GRID | 0) + b % GRID));
  const RANK = new Array(N);
  ORDER.forEach((k, r) => { RANK[k] = r / (N - 1); });

  const PHASES = [
    { key: "embed", dur: 3.6,
      cap: "<strong>1 &middot; Embed.</strong> Each block's 32-bit keyed signature and the " +
           "96-bit backup of a far-away block sink into the two lowest bits of its pixels." },
    { key: "quiet", dur: 2.2,
      cap: "<strong>2 &middot; Protected.</strong> Only the two least-significant bits moved " +
           "(the thin plane underneath). Around 43&nbsp;dB PSNR &mdash; the picture looks identical." },
    { key: "tamper", dur: 2.8,
      cap: "<strong>3 &middot; Tampered.</strong> A pen stroke scribbles across the grid, " +
           `overwriting ${FLAGGED} of ${N} blocks &mdash; pixels, signature and backup together.` },
    { key: "detect", dur: 2.8,
      cap: "<strong>4 &middot; Detect.</strong> Every signature is recomputed from the pixels " +
           "in front of it. A mismatch localises the damage to that one block, not to the image." },
    { key: "recover", dur: 4.6,
      cap: "<strong>5 &middot; Recover.</strong> Each flagged block is rebuilt from the backup " +
           `its intact partner still carries. ${LOST} blocks lost their partner to the same ` +
           "stroke and are marked magenta rather than filled with invented pixels." },
  ];
  const CYCLE = PHASES.reduce((a, p) => a + p.dur, 0);

  function phaseAt(t) {
    let x = t % CYCLE;
    for (let i = 0; i < PHASES.length; i++) {
      if (x < PHASES[i].dur) return { i, key: PHASES[i].key, u: x / PHASES[i].dur };
      x -= PHASES[i].dur;
    }
    return { i: PHASES.length - 1, key: "recover", u: 1 };
  }

  /* --- camera ------------------------------------------------------------ */

  // Spacing 1.16 against a side of 1.0 is a taste call with a reason: at a tight
  // 1.05 the 0.05 gap is narrower than the side wall you see through it, and each
  // tower looks like it has a wedge bitten out of its near corner. Wide enough to
  // read as deliberate separation, and the lattice stays legible.
  const S = 1.16;                       // grid spacing; box side is 1.0
  // Pitch is a real 3/4 top-down (~49 deg), not a shallow 33: at a shallow angle
  // the far rows hide behind the near ones and the grid reads as a wall.
  const cam = { yaw: -0.70, pitch: 0.85, dist: 25, focal: 30, scale: 30, cx: 0, cy: 0 };
  // Idle motion OSCILLATES about baseYaw rather than rotating continuously. A
  // full rotation looks fine for three quarters of its period and then passes
  // through yaw = 0, where every column of the grid lines up behind itself and
  // the model briefly turns into a flat lattice. Swinging +-15 deg never reaches
  // that angle, and a slow sine has no visible start or stop. Dragging still
  // reaches any angle -- that is the visitor's choice, not the idle animation's.
  const SWING = 0.26, SWING_HZ = 0.24;
  let baseYaw = cam.yaw, autoOrbit = true, idleAt = 0, swingT0 = 0;

  function project(x, y, z) {
    const cy1 = Math.cos(cam.yaw), sy1 = Math.sin(cam.yaw);
    const rx = x * cy1 - z * sy1;
    const rz = x * sy1 + z * cy1;
    const cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
    const ry = y * cp - rz * sp;
    const rz2 = y * sp + rz * cp;
    const d = cam.focal / (cam.focal + rz2 + cam.dist);
    return [cam.cx + rx * d * cam.scale, cam.cy - ry * d * cam.scale, rz2];
  }

  // Back-face cull by projected winding, which needs no normals and stays
  // correct at every yaw -- including the two where a side face is edge-on.
  function poly(pts, fill, stroke) {
    let area = 0;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], b = pts[(i + 1) % pts.length];
      area += a[0] * b[1] - b[0] * a[1];
    }
    if (area <= 0) return;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
  }

  // One box. Top face lit, sides stepped down -- the only lighting model here,
  // and enough: constant faces read as solid geometry, gradients read as glass.
  function box(x, yTop, z, side, h, colour, alpha, outline) {
    const s = side / 2, yBot = yTop - h;
    const t = [project(x - s, yTop, z - s), project(x + s, yTop, z - s),
               project(x + s, yTop, z + s), project(x - s, yTop, z + s)];
    const b = [project(x - s, yBot, z - s), project(x + s, yBot, z - s),
               project(x + s, yBot, z + s), project(x - s, yBot, z + s)];
    ctx.globalAlpha = alpha;
    for (let i = 0; i < 4; i++) {
      const j = (i + 1) % 4;
      poly([t[i], t[j], b[j], b[i]], shade(colour, i % 2 ? 0.62 : 0.78));
    }
    poly(t, shade(colour, 1), outline || null);
    ctx.globalAlpha = 1;
  }

  // Bezier in world space, projected per sample: the backup travelling from the
  // intact partner to the block being rebuilt.
  function arc(from, to, lift, colour, alpha, dash) {
    const mid = [(from[0] + to[0]) / 2, Math.max(from[1], to[1]) + lift, (from[2] + to[2]) / 2];
    ctx.beginPath();
    for (let i = 0; i <= 22; i++) {
      const u = i / 22, v = 1 - u;
      const p = project(v * v * from[0] + 2 * v * u * mid[0] + u * u * to[0],
                        v * v * from[1] + 2 * v * u * mid[1] + u * u * to[1],
                        v * v * from[2] + 2 * v * u * mid[2] + u * u * to[2]);
      i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    }
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = rgba(colour, 1);
    ctx.lineWidth = 1.6;
    ctx.setLineDash(dash ? [3, 3] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  const gx = (k) => (k % GRID - (GRID - 1) / 2) * S;
  const gz = ((k) => ((k / GRID | 0) - (GRID - 1) / 2) * S);

  /* --- one frame --------------------------------------------------------- */

  function draw(t) {
    if (!theme) theme = readTheme();
    const T = theme;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;                  // view is display:none -- nothing to do
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const pw = Math.round(w * dpr), pnh = Math.round(h * dpr);
    if (canvas.width !== pw || canvas.height !== pnh) {
      canvas.width = pw;
      canvas.height = pnh;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    cam.cx = w / 2;
    cam.cy = h * 0.56;
    cam.scale = Math.min(w * 0.079, h * 0.168);

    const ph = phaseAt(t);
    if (capEl && capEl.dataset.phase !== String(ph.i)) {
      capEl.dataset.phase = String(ph.i);
      capEl.innerHTML = PHASES[ph.i].cap;
    }

    // Per-block state for this frame. Collected first, drawn after sorting.
    // The sort key is the grid CELL's depth, not each box's own centre: boxes
    // in one cell differ wildly in height during the animation, and centre
    // depth then puts a tall lifted block behind the flat one in front of it.
    // Cell depth is exact for occlusion between cells, and within a cell the
    // lower box is always the farther one, so height breaks the tie.
    const items = [];
    const pushBox = (cz, x, y, z, side, hh, col, al, out) =>
      items.push({ cz, y, f: () => box(x, y, z, side, hh, col, al, out) });

    const lsbAlpha = ph.key === "embed" ? clamp01((ph.u - 0.6) / 0.4)
                   : ph.key === "quiet" ? 1
                   : 0.62;

    for (let k = 0; k < N; k++) {
      const x = gx(k), z = gz(k);
      const cz = project(x, 0, z)[2];
      let y = 0, col = T.block, al = 1, out = rgba(T["--border-strong"], 0.9);

      if (ph.key === "embed") {
        // Signature and backup slabs rise from below and fold into the pixel
        // block -- two payloads, one carrier, which is the whole trick. They
        // end AT the block and fade out there rather than parking underneath,
        // so the phase reads as "absorbed", and the travel is short enough to
        // stay inside the frame at every camera angle.
        const u = clamp01((ph.u - RANK[k] * 0.35) / 0.6);
        const e = ease(u);
        if (e < 0.995) {
          const fade = 0.9 * (1 - e) ** 0.7;
          pushBox(cz, x, lerp(-4.2, -0.3, e), z, 0.86, 0.28, T["--accent"], fade);
          pushBox(cz, x, lerp(-6.8, -0.3, e), z, 0.86, 0.42, T["--accent-hover"], fade);
        }
        al = 0.3 + 0.7 * e;
      } else if (ph.key === "quiet") {
        y = 0.04 * Math.sin(t * 1.6 + RANK[k] * 6.0);   // breathing, barely there
      } else if (ph.key === "tamper") {
        if (TAMPERED[k]) {
          const u = clamp01((ph.u - RANK[k] * 0.55) / 0.45);
          const e = ease(u);
          col = mixc(T.block, T["--bad"], e);
          y = e * (0.55 + JITTER[k][1] * 0.5);
        }
      } else if (ph.key === "detect") {
        // A scan plane crosses the grid; blocks it has passed carry a verdict.
        const front = -4.6 + ph.u * 9.2;
        const passed = x <= front;
        if (TAMPERED[k]) {
          col = T["--bad"];
          y = 0.55 + JITTER[k][1] * 0.5 + (passed ? 0.55 : 0);
          out = passed ? rgba(T["--bad"], 1) : out;
        } else if (passed) {
          out = rgba(T["--ok"], 0.85);
        }
      } else {                                            // recover
        if (TAMPERED[k]) {
          // Staggered along the same diagonal wave: partner lights, backup
          // travels, block settles back into the plane.
          const u = clamp01((ph.u - 0.06 - RANK[k] * 0.42) / 0.5);
          const e = ease(u);
          if (UNREC[k]) {
            col = T.unrec;
            y = 1.1 + Math.sin(t * 3.0 + k) * 0.06;       // stays up, stays marked
            out = rgba(T.unrec, 1);
          } else {
            // Ends bluish rather than back at plain grey: a recovered block is
            // rebuilt, not restored, and the model should not claim otherwise.
            col = mixc(T["--bad"], T.fixed, e);
            y = (1 - e) * 1.1;
            if (e > 0.02 && e < 0.98) out = rgba(T["--accent"], 1);
          }
        } else if (DONOR_OF[k] >= 0) {
          // A donor block: pulse while its backup is in flight.
          const u = clamp01((ph.u - 0.06 - RANK[DONOR_OF[k]] * 0.42) / 0.5);
          if (u > 0 && u < 1) { col = mixc(T.block, T["--accent"], 0.6); y = 0.18; }
        }
      }

      if (lsbAlpha > 0) {
        pushBox(cz, x, -0.72, z, 0.92, 0.18, T["--accent"], 0.40 * lsbAlpha);
      }
      pushBox(cz, x, y, z, 1.0, 0.55, col, al, out);
    }

    items.sort((a, b) => (b.cz - a.cz) || (a.y - b.y));   // far cells first, low boxes first
    for (const it of items) it.f();

    if (ph.key === "recover") {
      for (let k = 0; k < N; k++) {
        if (!TAMPERED[k] || UNREC[k]) continue;
        const u = clamp01((ph.u - 0.06 - RANK[k] * 0.42) / 0.5);
        if (u <= 0.02 || u >= 0.98) continue;
        const p = PARTNER[k];
        arc([gx(p), 0.02, gz(p)], [gx(k), (1 - ease(u)) * 1.1 + 0.02, gz(k)],
            2.4, theme["--accent"], 0.85 * Math.sin(u * Math.PI), true);
      }
    }
  }

  /* --- loop and interaction ---------------------------------------------- */

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let t0 = null;

  function tick(ms) {
    if (t0 === null) t0 = ms;
    // Frozen at the end of the recover phase when the visitor asked for less
    // motion: the most informative single pose, and still orbitable by hand.
    const t = reduced.matches ? CYCLE - 0.35 : (ms - t0) / 1000;
    // Phase-shifted so the swing is always AT ZERO the instant it resumes after
    // a drag. Without that, the sine picks up at whatever value it would have
    // held and the model snaps up to 15 degrees sideways the moment you stop.
    cam.yaw = baseYaw + (autoOrbit && !reduced.matches && ms > idleAt
                         ? SWING * Math.sin((t - swingT0) * SWING_HZ) : 0);
    draw(t);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  let drag = null;
  canvas.style.touchAction = "none";
  canvas.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, yaw: cam.yaw, pitch: cam.pitch };
    baseYaw = cam.yaw;                      // freeze the swing where it stands
    canvas.setPointerCapture(e.pointerId);
    canvas.classList.add("is-grabbing");
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    baseYaw = drag.yaw + (e.clientX - drag.x) * 0.007;
    cam.pitch = Math.max(0.12, Math.min(1.4, drag.pitch + (e.clientY - drag.y) * 0.005));
  });
  const release = () => {
    if (!drag) return;
    drag = null;
    canvas.classList.remove("is-grabbing");
    idleAt = performance.now() + 3500;      // let the visitor look before drifting again
    swingT0 = (idleAt - t0) / 1000;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);

  // Keyboard equivalent, because a drag-only control is not a control for
  // everyone. The canvas is focusable in the markup for exactly this.
  canvas.addEventListener("keydown", (e) => {
    const step = 0.12;
    if (e.key === "ArrowLeft") baseYaw -= step;
    else if (e.key === "ArrowRight") baseYaw += step;
    else if (e.key === "ArrowUp") cam.pitch = Math.min(1.4, cam.pitch + step / 2);
    else if (e.key === "ArrowDown") cam.pitch = Math.max(0.12, cam.pitch - step / 2);
    else if (e.key === " " || e.key === "Enter") autoOrbit = !autoOrbit;
    else return;
    e.preventDefault();
    idleAt = performance.now() + 3500;
    swingT0 = (idleAt - t0) / 1000;
  });
})();
