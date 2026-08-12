"use strict";

/* ===========================================================================
   Watermark Studio -- front end

   Five views, one hash router, no framework and no build step. Every number
   shown here comes verbatim from the server, which in turn takes it verbatim
   from src/. Nothing is recomputed in the browser.
   =========================================================================== */

const $ = (id) => document.getElementById(id);
const state = {
  protectSource: "sample",
  protectFile: null,
  verifyFile: null,
  wmSrc: null, diffSrc: null, wmCaption: "",
  stageTabs: [], verifyTabs: [],
};

/* --- plumbing ------------------------------------------------------------- */

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch { /* non-JSON error page -- fall through */ }
  if (!res.ok) throw new Error(data.error || `Request failed (HTTP ${res.status})`);
  return data;
}

const postJSON = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

// Record names come from uploaded filenames, so they are attacker-controlled text
// that this app then puts into innerHTML. Escaping is not optional here.
function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtNum(v, digits = 2) {
  if (v === "inf" || v === "-inf") return "∞";
  if (v === "nan" || v === null || v === undefined) return "n/a";
  return typeof v === "number" ? v.toFixed(digits) : String(v);
}
const fmtPct = (v, d = 1) => (typeof v === "number" ? (v * 100).toFixed(d) + "%" : fmtNum(v));
const fmtInt = (v) => (typeof v === "number" ? v.toLocaleString() : String(v));
const fmtBytes = (n) => (n >= 1048576 ? (n / 1048576).toFixed(2) + " MB"
                                      : Math.round(n / 1024) + " KB");

function setStatus(el, msg, { loading = false, error = false } = {}) {
  el.classList.toggle("err", !!error);
  el.innerHTML = loading ? `<span class="spinner" aria-hidden="true"></span>${esc(msg)}`
                         : esc(msg);
}

async function withBusy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } finally { btn.disabled = false; }
}

const stat = (k, v, x) =>
  `<div class="stat"><div class="stat-k">${esc(k)}</div>` +
  `<div class="stat-v">${v}</div><div class="stat-x">${x || ""}</div></div>`;

const show = (el, on = true) => { el.hidden = !on; };

function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

/* --- theme ---------------------------------------------------------------- */

function currentlyDark() {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr ? attr === "dark"
              : window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function paintThemeButton() {
  const dark = currentlyDark();
  $("theme-icon").textContent = dark ? "◑" : "◐";
  $("theme-label").textContent = dark ? "Light" : "Dark";
}

function initTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "dark" || saved === "light") {
    document.documentElement.setAttribute("data-theme", saved);
  }
  paintThemeButton();
  $("theme-toggle").addEventListener("click", () => {
    const next = currentlyDark() ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    paintThemeButton();
  });
}

/* --- router --------------------------------------------------------------- */

function goto(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("is-active"));
  document.querySelectorAll(".nav-item").forEach((n) =>
    n.classList.toggle("is-active", n.dataset.view === view));
  const el = $(`view-${view}`);
  (el || $("view-protect")).classList.add("is-active");
  if (location.hash !== `#${view}`) location.hash = view;
  window.scrollTo({ top: 0, behavior: "instant" });
  if (view === "library") loadLibrary();
}

$("nav").addEventListener("click", (e) => {
  const btn = e.target.closest(".nav-item");
  if (btn) goto(btn.dataset.view);
});
window.addEventListener("hashchange", () => goto(location.hash.slice(1) || "protect"));

/* --- reusable dropzone ---------------------------------------------------- */

function wireDrop(dropId, inputId, fileId, onPick) {
  const drop = $(dropId), input = $(inputId), out = $(fileId);
  const accept = (file) => {
    if (!file) return;
    out.hidden = false;
    out.innerHTML = `<strong>${esc(file.name)}</strong> &middot; ${fmtBytes(file.size)}`;
    onPick(file);
  };
  input.addEventListener("change", () => accept(input.files[0]));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add("is-over");
  }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove("is-over");
  }));
  drop.addEventListener("drop", (e) => accept(e.dataTransfer?.files?.[0]));
}

/* --- tab strips ----------------------------------------------------------- */

function renderTabs(stripId, imgId, capId, tabs) {
  const strip = $(stripId);
  strip.innerHTML = tabs.map((t, i) =>
    `<button class="tab${i === 0 ? " is-active" : ""}" data-i="${i}">${esc(t.label)}</button>`
  ).join("");
  const pick = (i) => {
    $(imgId).src = tabs[i].src;
    $(capId).innerHTML = tabs[i].explain;
    strip.querySelectorAll(".tab").forEach((b, j) => b.classList.toggle("is-active", j === i));
  };
  strip.onclick = (e) => {
    const b = e.target.closest(".tab");
    if (b) pick(Number(b.dataset.i));
  };
  pick(0);
}

/* ===========================================================================
   PROTECT
   =========================================================================== */

// Switch the Protect page between its two source panes. Called by the segmented
// control and also on load, when an absent corpus forces the Upload pane.
function selectSource(which) {
  state.protectSource = which;
  document.querySelectorAll(".seg-btn").forEach((b) => {
    const on = b.dataset.src === which;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-selected", String(on));
  });
  $("src-sample").classList.toggle("is-active", which === "sample");
  $("src-upload").classList.toggle("is-active", which === "upload");
}

async function loadSamples() {
  const sel = $("sample-select");
  const note = $("sample-note");
  try {
    const d = await api("/api/samples");
    sel.innerHTML = d.samples.map((s) =>
      `<option value="${esc(s.relpath)}">${esc(s.dataset)} / ${esc(s.filename)} ` +
      `(${s.width}×${s.height})</option>`).join("");
    const lena = d.samples.findIndex((s) => s.filename.toLowerCase().includes("lena"));
    if (lena >= 0) sel.selectedIndex = lena;

    note.hidden = !d.hint;
    if (d.hint) note.innerHTML = esc(d.hint).replace(/'([^']+)'/g, "<code>$1</code>");

    // With no corpus on disk, the sample pane is a dead end: default to Upload and
    // disable the empty picker rather than let the first click fail.
    if (!d.samples.length) {
      sel.innerHTML = '<option value="">No sample images downloaded</option>';
      sel.disabled = true;
      document.querySelector('.seg-btn[data-src="sample"]').disabled = true;
      selectSource("upload");
    }
  } catch (e) {
    sel.innerHTML = "<option value=\"\">Could not load the sample list</option>";
    sel.disabled = true;
    note.hidden = false;
    note.textContent = e.message;
    selectSource("upload");
  }
}

document.querySelectorAll(".seg-btn").forEach((btn) =>
  btn.addEventListener("click", () => selectSource(btn.dataset.src)));

wireDrop("protect-drop", "upload-input", "protect-file", (f) => { state.protectFile = f; });

// Variant C only exists at block size 8 (src/payload.py's C_DESC_BITS table is defined
// only at that width) -- the server 400s the combination, but disabling the option here
// means the mismatch can never be sent in the first place.
function syncVariantForBlock() {
  const block = parseInt($("block-select").value, 10);
  const variantSel = $("variant-select");
  const cOpt = variantSel.querySelector('option[value="C"]');
  if (block !== 8) {
    if (variantSel.value === "C") variantSel.value = "A";
    cOpt.disabled = true;
  } else {
    cOpt.disabled = false;
  }
}
$("block-select").addEventListener("change", syncVariantForBlock);
syncVariantForBlock();

function resetProtectDownstream() {
  ["protect-test", "damage-out", "check-out", "repair-out"].forEach((id) => show($(id), false));
  ["damage-status", "check-status", "repair-status"].forEach((id) => { $(id).textContent = ""; });
}

// Shared by the main "Protect this image" button and the per-page controls that
// appear once an upload turns out to have more than one page (a multi-page PDF).
async function runProtect(pageNum) {
  const st = $("protect-status");
  setStatus(st, "Embedding the watermark…", { loading: true });
  try {
    const body = {
      key: $("key-input").value,
      image_id: $("id-input").value,
      block: parseInt($("block-select").value, 10),
      variant: $("variant-select").value,
      page: pageNum || 1,
    };
    if (state.protectSource === "upload") {
      if (!state.protectFile) throw new Error("Choose a file to protect first.");
      body.upload_b64 = await fileToDataURL(state.protectFile);
      body.filename = state.protectFile.name;
    } else {
      body.sample = $("sample-select").value;
    }
    const d = await postJSON("/api/protect", body);

    $("img-original").src = d.original;
    $("img-watermarked").src = d.watermarked;
    state.wmSrc = d.watermarked;
    state.diffSrc = d.diff;
    state.wmCaption = `Protected — ${fmtInt(d.blocks)} blocks of ` +
      `${d.block}×${d.block}, ${d.width}×${d.height} px`;
    $("wm-caption").textContent = state.wmCaption;
    $("diff-toggle").checked = false;

    $("protect-stats").innerHTML = [
      stat("PSNR", fmtNum(d.psnr, 2) + " dB",
           "Above 40 dB the change is invisible to the eye."),
      stat("SSIM", fmtNum(d.ssim, 4), "1.0000 would be a pixel-perfect match."),
      stat("Blocks", fmtInt(d.blocks), `Each carries a 32-bit tag and a 96-bit backup.`),
      stat("File", fmtBytes(d.bytes), "Lossless PNG — the watermark survives saving."),
    ].join("");

    const srcNote = $("protect-source-note");
    srcNote.hidden = !d.source_note;
    if (d.source_note) srcNote.textContent = d.source_note;

    $("saved-badge").textContent = `Saved to library as #${d.record_id}`;
    $("download-protected").href = `/api/library/${d.record_id}/download`;
    $("id-input").value = d.image_id;
    $("rect-y1").value = Math.min(96, d.height);
    $("rect-x1").value = Math.min(96, d.width);

    const pagesWrap = $("protect-pages");
    if (d.pages_available > 1) {
      $("page-select").innerHTML = Array.from({ length: d.pages_available }, (_, i) =>
        `<option value="${i + 1}"${i + 1 === d.page ? " selected" : ""}>` +
        `Page ${i + 1} of ${d.pages_available}</option>`).join("");
      $("protect-all-btn").textContent = `Protect all ${d.pages_available} pages`;
      show(pagesWrap, true);
    } else {
      show(pagesWrap, false);
    }

    show($("protect-result"));
    resetProtectDownstream();
    show($("protect-test"));
    setStatus(st, "Done — the two images below are indistinguishable, which is the point.");
    updateNavCount(d.library_size);
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}

$("protect-btn").addEventListener("click", () => withBusy($("protect-btn"), () => {
  show($("protect-all-result"), false);
  return runProtect(1);
}));

$("protect-page-btn").addEventListener("click", () => withBusy($("protect-page-btn"), () =>
  runProtect(parseInt($("page-select").value, 10) || 1)));

function protectAllCard(r) {
  return `
    <div class="lib-card">
      <img src="${r.thumb}" alt="${esc(r.name)}">
      <div>
        <div class="lib-name">${esc(r.name)}</div>
        <div class="lib-meta">
          #${r.record_id} &middot; ${fmtInt(r.blocks)} blocks<br>
          PSNR ${fmtNum(r.psnr, 2)} dB &middot; SSIM ${fmtNum(r.ssim, 4)}
        </div>
      </div>
      <div class="lib-actions">
        <a class="btn btn-sm" href="/api/library/${r.record_id}/download" download>Download</a>
      </div>
    </div>`;
}

$("protect-all-btn").addEventListener("click", () => withBusy($("protect-all-btn"), async () => {
  const st = $("protect-all-status");
  setStatus(st, "Protecting every page…", { loading: true });
  try {
    if (!state.protectFile) throw new Error("Choose a file to protect first.");
    const body = {
      key: $("key-input").value,
      image_id: $("id-input").value,
      block: parseInt($("block-select").value, 10),
      variant: $("variant-select").value,
      upload_b64: await fileToDataURL(state.protectFile),
      filename: state.protectFile.name,
    };
    const d = await postJSON("/api/protect/all", body);
    $("protect-all-grid").innerHTML = d.results.map(protectAllCard).join("");
    $("protect-all-badge").textContent =
      `${d.count} page${d.count === 1 ? "" : "s"} protected — library now ${d.library_size}`;
    show($("protect-all-result"));
    updateNavCount(d.library_size);
    setStatus(st, "Done.");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

$("diff-toggle").addEventListener("change", (e) => {
  $("img-watermarked").src = e.target.checked ? state.diffSrc : state.wmSrc;
  $("wm-caption").textContent = e.target.checked
    ? "Hidden watermark, amplified ×50 — the real difference is far too small to see"
    : state.wmCaption;
});

$("goto-verify").addEventListener("click", () => goto("verify"));

/* --- damage / check / repair, in session ---------------------------------- */

async function doDamage(body) {
  const st = $("damage-status");
  setStatus(st, "Damaging…", { loading: true });
  try {
    const d = await postJSON("/api/damage", body);
    $("img-tampered").src = d.tampered;
    $("tampered-caption").textContent =
      `Damaged — ${d.kind} preset, ${fmtPct(d.achieved_ratio)} of the image ` +
      `(rows ${d.rect[0]}–${d.rect[2]}, cols ${d.rect[1]}–${d.rect[3]})`;
    show($("damage-out"));
    show($("check-out"), false);
    show($("repair-out"), false);
    setStatus(st, "Damage applied.");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}

document.querySelectorAll("#protect-test .btn-row .btn").forEach((btn) =>
  btn.addEventListener("click", () => withBusy(btn, () => doDamage({ kind: btn.dataset.kind }))));

$("damage-exact-btn").addEventListener("click", () => withBusy($("damage-exact-btn"), () =>
  doDamage({ rect: ["rect-y0", "rect-x0", "rect-y1", "rect-x1"]
    .map((id) => parseInt($(id).value, 10) || 0) })));

function paintVerdict(bannerId, iconId, textId, tampered, text) {
  const b = $(bannerId);
  b.classList.remove("tampered", "authentic");
  b.classList.add(tampered ? "tampered" : "authentic");
  $(iconId).textContent = tampered ? "⚠" : "✓";
  $(textId).textContent = text;
}

$("check-btn").addEventListener("click", () => withBusy($("check-btn"), async () => {
  const st = $("check-status");
  setStatus(st, "Recomputing every block signature…", { loading: true });
  try {
    const d = await postJSON("/api/check", {});
    const tampered = d.verdict === "TAMPERED";
    paintVerdict("verdict-banner", "verdict-icon", "verdict-text", tampered,
      tampered ? `TAMPERED — ${fmtInt(d.flagged_blocks)} of ${fmtInt(d.total_blocks)} blocks flagged`
               : `AUTHENTIC — all ${fmtInt(d.total_blocks)} blocks verify`);
    const note = $("suspect-note");
    note.hidden = !d.suspect_message;
    if (d.suspect_message) note.textContent = "⚠ " + d.suspect_message;

    const same = d.raw_overlay === d.refined_overlay;
    renderTabs("stage-tabs", "stage-img", "stage-caption", [
      { label: "Raw flags", src: d.raw_overlay,
        explain: "Every block whose recomputed signature failed, before any cleanup." },
      { label: "Refined", src: d.refined_overlay,
        explain: same
          ? "A neighbourhood pass fills gaps surrounded by flagged blocks. This damage is one solid region with no gaps, so there is nothing to fill — identical to the raw flags, which is the honest result rather than a staged difference."
          : "A neighbourhood pass closed small gaps inside the tampered region." },
      { label: "Pixel mask", src: d.pixel_overlay,
        explain: "The same block decision expanded to pixel resolution — exactly the region repair will target." },
    ]);

    $("loc-stats").innerHTML = [
      stat("Precision", fmtPct(d.precision), "Of what was flagged, this share really was tampered."),
      stat("Recall", fmtPct(d.recall), "Of what was really tampered, this share was caught."),
      stat("F1", fmtPct(d.f1), "Precision and recall in one number."),
      stat("IoU", fmtPct(d.iou), "Overlap between the flagged and the real damaged region."),
    ].join("");

    show($("check-out"));
    show($("repair-out"), false);
    setStatus(st, "Detection complete.");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

function repairStats(d) {
  const unrec = d.counts.unrecoverable;
  return [
    stat("Coverage", fmtPct(d.rho),
      unrec > 0
        ? `${fmtInt(unrec)} of ${fmtInt(d.counts.tampered)} damaged blocks had their backup destroyed too.`
        : "Every backup needed was intact."),
    stat("PSNR in region", fmtNum(d.psnr_in_region, 2) + " dB",
      "Repaired vs. original, inside the damaged area only."),
    stat("PSNR whole image", fmtNum(d.psnr_whole, 2) + " dB",
      "Repaired vs. original, across the entire image."),
    stat("SSIM in region", fmtNum(d.ssim_in_region, 4),
      "Structural similarity inside the repaired area."),
  ].join("");
}

/* --- cosmetic gap fill ----------------------------------------------------- */

// Both repair panels offer the same toggle, so they share one wiring function --
// the same reason demo/app.py has a single effective_variant() helper. The toggle
// is HIDDEN, not merely unchecked, when nothing is unrecoverable: an inpaint
// switch on an image with no gaps invites the reader to think something was
// filled in. Nothing here touches the numbers in repairStats -- those come from
// recover_image's real output, where the gaps are still marked.
function wireFill(toggleId, rowId, imgId, capId, d) {
  const row = $(rowId), tog = $(toggleId), img = $(imgId), cap = $(capId);
  const lost = (d.counts && d.counts.unrecoverable) || 0;
  const MARKED = "Repaired — magenta hatch marks blocks that could not be recovered";
  const FILLED = "Repaired, with the unrecoverable gaps interpolated — those pixels are " +
                 "a guess from their neighbours, not watermark data, and are excluded from " +
                 "every number below";
  tog.checked = false;
  img.src = d.overlay;
  cap.textContent = lost ? MARKED : "Repaired — every flagged block was recoverable";
  show(row, lost > 0);
  tog.onchange = () => {
    img.src = tog.checked ? d.filled : d.overlay;
    cap.textContent = tog.checked ? FILLED : MARKED;
  };
}

$("repair-btn").addEventListener("click", () => withBusy($("repair-btn"), async () => {
  const st = $("repair-status");
  setStatus(st, "Rebuilding from the hidden backups…", { loading: true });
  try {
    const d = await postJSON("/api/repair", {});
    wireFill("fill-toggle", "fill-row", "img-repaired", "repair-caption", d);
    $("repair-stats").innerHTML = repairStats(d);
    show($("repair-out"));
    setStatus(st, "Repair complete.");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

/* ===========================================================================
   VERIFY AN UPLOAD
   =========================================================================== */

wireDrop("verify-drop", "verify-input", "verify-file", (f) => {
  state.verifyFile = f;
  $("verify-btn").disabled = false;
});

function matchCard(d) {
  const m = d.matched;
  const ident = d.identification;
  const runner = ident.runner_up;
  const tried = ident.candidates_tried.length;
  const sep = runner
    ? `The next-closest of ${tried} same-size records has ${fmtInt(runner.verifying_blocks)} ` +
      `blocks verifying — that is what a wrong key looks like, and it is why this match is ` +
      `unambiguous.`
    : `It is the only image in the library at ${m.width}×${m.height}.`;
  return `
    <img src="/api/library/${m.id}/thumb" alt="Stored copy of ${esc(m.name)}">
    <div class="match-body">
      <div class="match-title">
        ${esc(m.name)}
        <span class="badge badge-ok">library #${m.id}</span>
        ${d.byte_identical ? '<span class="badge badge-ok">byte-identical</span>'
                           : '<span class="badge badge-bad">bytes differ</span>'}
      </div>
      <p class="lead">Identified by keyed verification, not by filename: this record's key and
        image identity are the ones that actually check out against these pixels.
        ${esc(sep)}</p>
      <table class="kv">
        <tr><td>Protected on</td><td>${esc(m.created_at)}</td></tr>
        <tr><td>Geometry</td><td>${m.width}×${m.height}, ${m.block}×${m.block} blocks,
          descriptor ${esc(m.variant)}</td></tr>
        <tr><td>Blocks still verifying</td><td>${fmtInt(ident.verifying_blocks)}
          of ${fmtInt(m.blocks)} &mdash; ${fmtInt(ident.min_verifying_blocks)} are enough to
          identify a file, because under the wrong key a block verifies only if all three
          channel tags collide (chance 2<sup>-96</sup>)</td></tr>
        <tr><td>Signature failures</td><td>${fmtPct(ident.flag_rate, 2)} of blocks</td></tr>
        <tr><td>Stored SHA-256</td><td><code>${esc(d.stored_sha256)}</code></td></tr>
        <tr><td>Uploaded SHA-256</td><td><code>${esc(d.uploaded_sha256)}</code></td></tr>
      </table>
    </div>`;
}

$("verify-btn").addEventListener("click", () => withBusy($("verify-btn"), async () => {
  const st = $("verify-status");
  const errNote = $("verify-error-note");
  show(errNote, false);
  setStatus(st, "Searching the library and verifying…", { loading: true });
  try {
    if (!state.verifyFile) throw new Error("Choose a file to verify first.");
    const d = await postJSON("/api/verify", {
      upload_b64: await fileToDataURL(state.verifyFile),
      filename: state.verifyFile.name,
    });
    renderVerifyResult(d);
    setStatus(st, "Verification complete.");
  } catch (e) {
    show($("verify-result"), false);
    // The most likely failure by far is a lossy upload (JPEG/WEBP/GIF, or a rasterised
    // PDF page) -- the server already explains exactly why in plain English, so that
    // explanation gets its own readable panel rather than being squeezed into the
    // one-line status text next to the button.
    setStatus(st, "Verification failed — see details below.", { error: true });
    errNote.textContent = e.message;
    show(errNote, true);
  }
}));

function renderVerifyResult(d) {
  $("match-card").innerHTML = matchCard(d);
  const tampered = d.verdict === "TAMPERED";
  paintVerdict("v-verdict-banner", "v-verdict-icon", "v-verdict-text", tampered,
    tampered
      ? `TAMPERED — ${fmtInt(d.flagged_blocks)} of ${fmtInt(d.total_blocks)} blocks flagged`
      : `AUTHENTIC — all ${fmtInt(d.total_blocks)} blocks verify against library #${d.matched.id}`);

  const note = $("v-suspect-note");
  note.hidden = !d.suspect_message;
  if (d.suspect_message) note.textContent = "⚠ " + d.suspect_message;

  $("verify-stats").innerHTML = [
    stat("Blocks flagged", fmtInt(d.flagged_blocks),
      `out of ${fmtInt(d.total_blocks)}, by signature mismatch alone`),
    stat("Pixels changed", fmtInt(d.changed_pixels),
      `${fmtPct(d.changed_ratio, 2)} of the image, measured against the stored copy`),
    stat("Recall", fmtPct(d.recall),
      "Of the region that really changed, this share was localized."),
    stat("IoU", fmtPct(d.iou),
      "Overlap between what detection flagged and what actually changed."),
  ].join("");

  renderTabs("verify-tabs", "verify-img", "verify-caption", [
    { label: "Detected", src: d.detected_overlay,
      explain: "Red marks every block the watermark flagged. Detection used only the uploaded file and the key — it never saw the stored copy." },
    { label: "What really changed", src: d.truth_overlay,
      explain: "Green marks the pixels that genuinely differ from the stored library copy. This is the ground truth the numbers above are scored against, and it is shown only after the fact." },
    { label: "Uploaded", src: d.uploaded_image, explain: "The file exactly as uploaded." },
    { label: "Stored original", src: d.stored_image,
      explain: "The protected copy held in the library, straight from the database." },
    { label: "Difference ×50", src: d.diff,
      explain: "Uploaded minus stored, amplified 50 times so even a single-bit edit becomes visible." },
  ]);

  const rb = $("v-repair-btn");
  rb.disabled = !d.repairable;
  rb.title = d.repairable ? "" : "Nothing to rebuild — this image is intact.";
  const rsb = $("v-restore-btn");
  rsb.disabled = !d.repairable;
  rsb.title = d.repairable ? "" : "Nothing to restore — this image is intact.";
  $("v-download-stored").href = `/api/library/${d.matched.id}/download`;
  show($("v-repair-out"), false);
  show($("v-restore-out"), false);
  $("v-repair-status").textContent = "";
  $("v-restore-status").textContent = "";
  show($("verify-result"));
}

$("v-repair-btn").addEventListener("click", () => withBusy($("v-repair-btn"), async () => {
  const st = $("v-repair-status");
  setStatus(st, "Rebuilding from the hidden backups…", { loading: true });
  try {
    const d = await postJSON("/api/verify/repair", {});
    wireFill("v-fill-toggle", "v-fill-row", "v-img-repaired", "v-repair-caption", d);
    $("v-repair-stats").innerHTML = repairStats(d);
    show($("v-repair-out"));
    setStatus(st, "Repair complete — quality measured against the stored original.");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

function restoreStats(d) {
  return [
    stat("Blocks restored", `${fmtInt(d.blocks_restored)} / ${fmtInt(d.total_blocks)}`,
      "Every one of these was copied byte-for-byte from the library archive, not rebuilt."),
    stat("Pixels changed", fmtInt(d.pixels_changed),
      "How many pixels differed from the archive copy before this restore."),
  ].join("");
}

$("v-restore-btn").addEventListener("click", () => withBusy($("v-restore-btn"), async () => {
  const st = $("v-restore-status");
  setStatus(st, "Copying the flagged blocks from the archive…", { loading: true });
  try {
    const d = await postJSON("/api/verify/restore", {});
    $("v-img-restored").src = d.restored;
    $("v-restore-stats").innerHTML = restoreStats(d);
    const badge = $("v-restore-badge");
    show(badge, !!d.bit_exact);
    if (d.bit_exact) badge.textContent = "bit-exact — 0 pixels differ from the archive";
    // Render the server's own explanation of what this endpoint did and did not do,
    // rather than writing a competing claim here.
    $("v-restore-note").textContent = d.note;
    show($("v-restore-out"));
    setStatus(st, "Restore complete.");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

/* ===========================================================================
   LIBRARY
   =========================================================================== */

function updateNavCount(n) {
  const el = $("nav-count");
  if (typeof n !== "number") return;
  el.hidden = n === 0;
  el.textContent = String(n);
}

function libCard(r) {
  return `
    <div class="lib-card" data-id="${r.id}">
      <img src="/api/library/${r.id}/thumb" alt="${esc(r.name)}" loading="lazy">
      <div>
        <div class="lib-name">${esc(r.name)}</div>
        <div class="lib-meta">
          #${r.id} &middot; ${r.width}×${r.height} &middot; ${r.block}×${r.block}
          &middot; variant ${esc(r.variant)}<br>
          PSNR ${fmtNum(r.psnr, 2)} dB &middot; SSIM ${fmtNum(r.ssim, 4)}<br>
          ${esc(r.created_at)}
        </div>
      </div>
      <div class="lib-actions">
        <a class="btn btn-sm" href="/api/library/${r.id}/download" download>Download</a>
        <button class="btn btn-sm" data-act="check" data-id="${r.id}">Check it</button>
        <button class="btn btn-sm btn-danger" data-act="delete" data-id="${r.id}">Delete</button>
      </div>
    </div>`;
}

async function loadLibrary() {
  const st = $("library-status");
  setStatus(st, "Loading…", { loading: true });
  try {
    const { records } = await api("/api/library");
    $("library-grid").innerHTML = records.map(libCard).join("");
    show($("library-empty"), records.length === 0);
    updateNavCount(records.length);
    setStatus(st, `${records.length} protected image${records.length === 1 ? "" : "s"} stored.`);
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}

$("library-refresh").addEventListener("click", loadLibrary);

$("library-grid").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.dataset.id;

  if (btn.dataset.act === "delete") {
    if (!window.confirm(`Permanently delete protected image #${id} from the library? ` +
                        `Any downloaded copy can no longer be verified.`)) return;
    await withBusy(btn, async () => {
      try {
        const d = await api(`/api/library/${id}`, { method: "DELETE" });
        updateNavCount(d.library_size);
        loadLibrary();
      } catch (err) {
        setStatus($("library-status"), err.message, { error: true });
      }
    });
    return;
  }

  // "Check it" round-trips the stored file back through the real upload path, so
  // what runs is the same verification an outside file would get -- not a shortcut.
  await withBusy(btn, async () => {
    const st = $("library-status");
    setStatus(st, `Verifying #${id} through the upload path…`, { loading: true });
    try {
      const blob = await (await fetch(`/api/library/${id}/download`)).blob();
      const b64 = await fileToDataURL(new File([blob], `library-${id}.png`, { type: "image/png" }));
      const d = await postJSON("/api/verify", { upload_b64: b64, filename: `library-${id}.png` });
      state.verifyFile = null;
      $("verify-file").hidden = false;
      $("verify-file").innerHTML = `<strong>library-${esc(id)}.png</strong> &middot; from the library`;
      $("verify-btn").disabled = true;
      renderVerifyResult(d);
      setStatus(st, "");
      goto("verify");
    } catch (err) {
      setStatus(st, err.message, { error: true });
    }
  });
});

/* ===========================================================================
   ATTACK LAB
   =========================================================================== */

function attackBanner(bad, text) {
  return `<div class="banner ${bad ? "tampered" : "authentic"}">` +
    `<span class="banner-icon" aria-hidden="true">${bad ? "⚠" : "✓"}</span>` +
    `<span>${esc(text)}</span></div>`;
}

$("transplant-btn").addEventListener("click", () => withBusy($("transplant-btn"), async () => {
  const st = $("transplant-status");
  setStatus(st, "Transplanting a valid signature…", { loading: true });
  try {
    const d = await postJSON("/api/attack/transplant", {});
    $("transplant-result").innerHTML = `
      <div class="compare">
        <figure><img src="${d.watermarked}" alt="Genuine protected image">
          <figcaption>Genuine protected image</figcaption></figure>
        <figure><img src="${d.transplanted}" alt="Forged image">
          <figcaption>Forged — block #${d.dest_block} replaced with pixels copied
            from block #${d.source_block}</figcaption></figure>
      </div>
      ${attackBanner(d.detection_fired,
        d.detection_fired ? `Detection FIRED at block #${d.dest_block}`
                          : "Detection did not fire — try another target block")}
      <p class="lead">${esc(d.explanation)}</p>`;
    show($("transplant-result"));
    setStatus(st, "");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

$("coincidence-btn").addEventListener("click", () => withBusy($("coincidence-btn"), async () => {
  const st = $("coincidence-status");
  setStatus(st, "Destroying a block and its only backup…", { loading: true });
  try {
    const d = await postJSON("/api/attack/coincidence", {});
    $("coincidence-result").innerHTML = `
      <div class="compare">
        <figure><img src="${d.tampered}" alt="Both blocks destroyed">
          <figcaption>Block #${d.block_index} and its backup partner
            #${d.partner_index}, both destroyed</figcaption></figure>
        <figure><img src="${d.repaired_overlay}" alt="Repair attempt">
          <figcaption>Repair attempt — magenta hatch marks what could not be
            rebuilt</figcaption></figure>
      </div>
      ${attackBanner(d.unrecoverable,
        d.unrecoverable
          ? `UNRECOVERABLE — block #${d.block_index} and partner #${d.partner_index} both lost`
          : "Recovered anyway — try another block index")}
      <p class="lead">${esc(d.explanation)}</p>`;
    show($("coincidence-result"));
    setStatus(st, "");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

$("evidence-btn").addEventListener("click", () => withBusy($("evidence-btn"), async () => {
  const st = $("evidence-status");
  setStatus(st, "Fetching…", { loading: true });
  try {
    const b = encodeURIComponent($("evidence-block").value);
    const c = encodeURIComponent($("evidence-channel").value);
    const d = await api(`/api/audit/${b}?channel=${c}`);
    $("evidence-card").innerHTML = `
      <span class="badge ${esc(d.decision)}">${esc(d.decision.replace(/_/g, " "))}</span>
      <p class="lead">${esc(d.reason)}</p>
      <table class="kv">
        <tr><td>Stored tag</td><td><code>${esc(d.stored_tag)}</code></td></tr>
        <tr><td>Recomputed tag</td><td><code>${esc(d.recomputed_tag)}</code></td></tr>
        <tr><td>Tags match</td><td>${d.tag_matched ? "yes" : "no"}</td></tr>
        <tr><td>Flagged before refinement</td><td>${d.flagged_raw ? "yes" : "no"}</td></tr>
        <tr><td>Flagged after refinement</td><td>${d.flagged_after_refinement ? "yes" : "no"}</td></tr>
        <tr><td>Partner block holding its backup</td><td>#${d.partner_block}</td></tr>
        <tr><td>Partner flagged too</td><td>${d.partner_flagged ? "yes" : "no"}</td></tr>
      </table>`;
    show($("evidence-card"));
    setStatus(st, "");
  } catch (e) {
    setStatus(st, e.message, { error: true });
  }
}));

/* --- init ----------------------------------------------------------------- */

initTheme();
loadSamples();
api("/api/library").then((d) => updateNavCount(d.records.length)).catch(() => {});
goto(location.hash.slice(1) || "protect");
