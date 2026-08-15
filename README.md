# Watermark-Guided Tamper Localization and Recovery

A self-embedding fragile watermarking scheme for images. Each 8x8 block is
split into a 32-bit keyed HMAC-SHA256 authentication tag (computed from the
block's own six most-significant bit-planes) and a 96-bit recovery descriptor
(a compressed low-frequency approximation of another, spatially distant
block), both embedded into the two least-significant bit-planes. Verification
recomputes each tag; a mismatch is tampering, and a flagged block is
reconstructed from the descriptor held by its (authentic) partner block, or
marked explicitly unrecoverable if that partner is also flagged. Everything is
deterministic, keyed, and training-free -- no ML, no GPU. Full methodology,
notation, and results are in `paper/IEEE_Paper.tex`.

That is the entire paper in one self-contained file -- no companion `.tex`, so it
uploads or converts as a single file. It used to pull its five tables in with
`\input{../output/tables/*.tex}`, which meant the printed numbers could never
disagree with the committed result grid, but also meant anything handed only the
one file stopped at `File '../output/tables/imperceptibility.tex' not found`.
The tables are now inlined verbatim instead, each between a marker comment and
the end of its tabular, and `python src/sync_paper_tables.py` rewrites every one
of those blocks from the current `output/tables/` files -- so re-run it after
regenerating the grid and the no-drift guarantee is back without the extra file.
The script ends in 37 structural checks (every table landed with its numbers,
environments and braces balance, every `\ref` resolves, every tabular row's cell
count matches its column spec).

The two figures are optional: drop `output/figures/recovery_vs_ratio.pdf` and
`qualitative_strip.pdf` beside the `.tex` to render them, or compile without them
and each becomes a labelled placeholder box rather than a fatal error.

### The project synopsis

`paper/Synopsis.tex` is the university project synopsis, a different document for
a different reader. It is deliberately **not** in IEEEtran: SPPU's Project Work
Book prescribes A4, single column, Times 12 pt at one-and-a-half spacing, and a
title page carrying student and guide signatures, none of which fits a two-column
conference template. It keeps IEEE's numbered `[n]` citations and reference
format, which the same workbook requires, and carries the sections the rubric
grades — including *Relevant Mathematics* and *Target Publication Venues*, the two
SPPU-specific items most groups omit. The IEEE paper is referenced as Annexure A
rather than duplicated. Every measured number in it comes from the same
`output/tables/` grid as the paper, so the two cannot disagree.

### Building the PDF and the Word documents

```bash
python src/build_docs.py                  # all four files
python src/build_docs.py --skip-pdf       # DOCX only, reusing the last LaTeX .aux
python src/build_docs.py --synopsis-only  # just the synopsis
```

Outputs land in `output/paper/`: `IEEE_Paper.pdf` (15 pages) and `IEEE_Paper.docx`,
plus `Synopsis.pdf` (18 pages) and `Synopsis.docx`. Needs [tectonic](https://tectonic-typesetting.github.io) and
[pandoc](https://pandoc.org) on `PATH`, or pointed at by `$TECTONIC` / `$PANDOC`.
Tectonic is a single binary that downloads the TeX packages it needs on first
run, so there is no TeX distribution to install.

**The PDF is the real thing.** Tectonic compiles the actual `IEEEtran` class, so
the layout is IEEE's own: US Letter, two columns, the genuine title block and
section numbering. The build reports the number of overfull boxes and currently
finds zero.

**The DOCX is a conversion, and the difference is worth stating plainly.** Word
has no `IEEEtran`, so the format is reconstructed rather than compiled -- IEEE
page size and margins, a single-column title block over a two-column body, Times
New Roman at IEEE sizes, centred roman-numeral section headings, italic lettered
subsections, 8 pt tables (7 pt for the nine-column one), wide tables given
full-page-width sections the way `table*` does in LaTeX, and figures at column
width. Cross-references and citation numbers are substituted from the `.aux`
tectonic just wrote, so the Word file's `(6)`, `Table II` and `[18]` are the same
numbers the PDF prints rather than an independent renumbering. What it is not is
byte-equal typesetting: line breaks, hyphenation and float placement are Word's,
not TeX's. **Submit the PDF; the DOCX is for people who need to edit or comment.**

The build ends in 27 checks over the produced files -- all five tables and both
figures present, math converted to Word equations, the section break and page
setup right, no LaTeX macro name left in the text, and the two layout invariants
that were genuinely wrong at one point: every table's columns must add up to its
declared width, and no table cell may keep the body's first-line indent, which
silently narrows a cell's first line and splits numbers like `0.9824` in half.

Three descriptor variants share that container. **A** keeps 12 zig-zag DCT
coefficients at a fixed 8 bits each; **B** keeps 2x2 block means; **C** is the
default, and spends the same 96 bits on 31-34 variable-width coefficient fields
chosen by rate-distortion optimization, plus one bit selecting between two
allocation tables. C measures **+3.43 dB mean and +2.52 dB worst-case** recovered
fidelity over A across 13 corpus images its tables were never fitted on -- so it is
never the worse choice -- and roughly +4 dB on scanned-document content, which is A's
worst case because text is broadband and 12 coefficients is a severe low-pass filter.
The paper's experiment grid reports A and B; C's tables and their measured gain are
reproduced by `python src/fit_variant_c.py`, which refits them and asserts they match
the shipped constants.

## Just want to use it?

**Setting this up on a new machine? Follow [INSTALL.md](INSTALL.md)** — every command
spelled out, including installing Python, with a troubleshooting section for the
things that actually go wrong.

Short version, once dependencies and the corpus are in place:

```bash
python webapp/server.py            # then open http://127.0.0.1:8765/
```

The real round trip it is built for:

1. **Protect an image** -- pick a corpus sample or upload your own file (PNG, JPEG,
   PDF, BMP, TIFF, WebP, GIF; PDFs page by page or all pages at once), embed the
   watermark, and **download the protected file**, always as PNG. It is also saved to
   a local library (`webapp/library.db`, SQLite) together with the key, the image
   identity bound into every HMAC, and the block geometry -- the three things without
   which a keyed fragile watermark cannot be checked again later.
2. **Edit that downloaded file** in any image editor, anywhere, and save it as PNG.
3. **Upload it under "Verify an upload."** The app works out *which* library record
   it is, compares it against the stored copy, and says where it was altered.

Repair then comes in two flavours, and the difference is the honest part:

- **Restore exactly from library** replaces the flagged blocks with the real bytes
  from the stored copy. The result is byte-identical to the file that was originally
  protected -- genuinely 100%, 0 unrecoverable, because the pixels come from the
  archive. The watermark's contribution is proving the upload *is* that record and
  localizing exactly which blocks changed, not reconstructing them. Worth stating
  plainly rather than dressing up: a verifying block is provably bit-identical to the
  stored one already (the tag pins all 512 bits of an 8x8 block), so restoring only
  the flagged blocks reproduces the stored file exactly -- and the endpoint asserts
  that equality rather than trusting it.
- **Rebuild from watermark only** is the scheme itself: it consults no archive and
  rebuilds flagged blocks from descriptors carried inside the surviving parts of the
  image. Approximate by construction, and it marks rather than fabricates where a
  block and its partner were both destroyed. This is the path the paper measures, and
  the one that still works on a machine that has never seen your library.

Only the second path can leave magenta blocks, and it cannot reach 100% by
construction: a 96-bit descriptor cannot carry 512 bits of block, and when a block
and the single block holding its backup are both destroyed there is nothing left to
read. If you want the file back exactly, that is what the first path is for -- it is
byte-identical, with no magenta anywhere.

For the second path there is one presentation affordance: a toggle that interpolates
the marked gaps away (`cosmetic_fill` in `webapp/server.py` and `demo/app.py`). It is
**off by default, cosmetic, and structurally quarantined**. Those pixels have no
cryptographic provenance -- every other pixel in a repair came from a descriptor
carried by a block whose tag verified; these came from an interpolator guessing at
the neighbours. It runs on a copy downstream of `recover_image`, its output reaches
no metric, and `/api/download/repaired` still serves the honestly-marked image, so
the fabricated one can never become the artifact you keep. `rho`, the unrecoverable
count and every PSNR/SSIM still report the gaps the filled picture no longer shows.
The toggle is hidden entirely when nothing is unrecoverable. `src/recover.py:139-142`
specified this discipline before the function existed.

Uploads for *verification* must be lossless (PNG/BMP/TIFF, or a PDF carrying one) --
a JPEG or WebP re-save discards precisely the two bit-planes the watermark occupies,
so the app refuses with that explanation instead of reporting phantom tampering
across the whole image. Protecting a lossy source is fine; only re-checking one is not.

Identification uses no filenames and no perceptual hashing: it simply asks which
record's key and image identity actually verify against these pixels. Under the
wrong key a block verifies only if all three of its channel tags collide (chance
2^-96), so a wrong record leaves essentially zero blocks verifying while the right
one leaves every untampered block verifying. Nine surviving blocks out of 4096 are
enough to name the file -- verified in the API test -- and a fully overwritten image
is refused rather than guessed at, because at that point nothing is left to identify
it by.

Also in the app: a "test it right here" path (damage -> detect -> repair without
leaving the page), a library view with per-record download/verify/delete, the two
adversarial set-pieces, and a per-block evidence panel. Flask plus hand-written
HTML/CSS/JS -- no build step, no CDN, no external network requests.

"How it works" opens with an animated 3-D model of the scheme (`webapp/static/scene3d.js`):
64 block towers over three planes, cycling embed -> protected -> tampered -> detect ->
recover, draggable and keyboard-orbitable. It is not decoration -- the block-to-partner
map is a fixed coprime stride like the real one, and a block turns magenta only when it
*and* its partner were both hit, which is the coincidence limit the Attack lab proves.
Canvas 2-D with a hand-written projector, depth sort and back-face cull, ~300 lines: a
CDN `<script>` would break the "nothing leaves this machine" claim on every page load,
and vendoring a WebGL library to draw 192 axis-aligned boxes is the other bad option.
Every colour is a design token read at run time, so the model re-themes with the app,
and `prefers-reduced-motion` freezes it on the recover pose rather than hiding it. `--port` and
`--host` are available if 8765 is taken; `WATERMARK_DB=<path>` points the library at
a different file, which is how the test suite avoids touching your real one.

`streamlit run demo/app.py` is a second, simpler interface over the same `src/`
pipeline, kept as a fallback for presenting. It has no library and no upload
verification -- those live only in `webapp/`.

One honest note on the library: it stores each image's key in the clear, in the same
row as the image. That is right for a local single-user tool and wrong for a
deployment, where keys belong in an OS keyring, HSM, or KMS and never beside the
artefact they authenticate. The scheme's entire security argument rests on the
attacker not holding the key.

## Reproducing the results

Run in this order -- each stage depends on the previous one's output:

```bash
python samples/fetch_corpus.py     # downloads + SHA-256-pins the 32-image corpus into samples/manifest.csv
python src/fit_variant_c.py        # re-derives variant C's tables; asserts they match payload.py
python src/test_e2e.py             # KEYSTONE GATE -- must pass before any other result is trusted
python src/run_experiments.py      # full 1,184-run grid -> output/runs.csv (use --quick for a 10-row smoke run)
python src/sanity_gate.py          # checks runs.csv against measured bands; must print "overall: PASS"
python src/make_tables.py          # runs.csv -> output/tables/*.tex  (aborts if the gate fails)
python src/plots.py                # runs.csv -> output/figures/
```

`src/test_e2e.py` is the keystone gate: it asserts that an untouched
watermarked image produces **zero** flagged blocks (the "null condition"), plus
the independent `m`/`minv` mapping-direction canary that the keystone assertion
alone cannot catch. No number from any later stage means anything if this
fails. It runs 50 combinations (5 images x 2 colour modes x block 4/8 for A and B,
plus block 8 for C, which is a block-8-only format) and pins 9 golden vectors of the
wire format. Variant C is gated there rather than merely available, because it is
what the app embeds by default and an ungated default is the exact thing the gate
exists to prevent; adding it left A's and B's golden vectors bit-identical, which is
the evidence that watermarks made before C still verify.

`src/sanity_gate.py` checks `runs.csv` against bands measured from this corpus,
and `src/make_tables.py` calls it first and refuses to emit tables if it fails --
so "generate tables from numbers nobody sanity-checked" is impossible through the
intended entry point. Note its scope honestly: it validates the results CSV, not
the generated LaTeX, and a hardcoded false figure once reached a printed table
through exactly that gap.

Every module in `src/` (`payload.py`, `blockmap.py`, `embed.py`, `detect.py`,
`recover.py`, `tamper.py`, `metrics.py`, `imageio_any.py`, `fit_variant_c.py`, ...)
is independently runnable and carries its own self-check (`python src/<module>.py`) -- none of them require
the full pipeline to verify their own piece in isolation. `python webapp/db.py`
does the same for the library layer, against an in-memory database so it can
never touch the real one.

## Corpus, provenance, and licensing

32 colour images: 8 USC-SIPI Miscellaneous-set images at 512x512, and 24 Kodak
PCD0992 images (18 at 768x512, 6 at 512x768). Fetched as redistributed by the
AuSR reference authors (`github.com/girfa/ColorImageDatasets`); original
sources are USC-SIPI (`sipi.usc.edu`) and Eastman Kodak (mirrored at
`r0k.us/graphics/kodak`) -- USC-SIPI no longer distributes two of these eight
images (Lena, Tiffany) from its own archive, so using the same redistributed
set the AuSR papers report on is both necessary and useful for comparability.
USC-SIPI is licensed for research/education use with attribution; Kodak
PCD0992 was released by Eastman Kodak for unrestricted use. Neither is
redistributed here commercially. Every image is SHA-256 pinned in the
committed `samples/manifest.csv`; a mismatch on re-fetch is a hard error, not
a silent drift.

## Reproducibility: key and image-ID convention

The numbers in the paper come from a deterministic research key,
`make_key(key_id)` in `src/run_experiments.py`, which returns
`b"wgtlr-research-key-%02d" % key_id`; `key_id=0` is the key used for the main
grid and the block-size ablation (a handful of additional key IDs are used
only for the null-condition implementation-robustness check, not for any
reported result). The image identifier bound into every HMAC is
`default_image_id(stem, shape, block)` in `src/payload.py`, a deterministic
`stem|HxW|B` string -- not a random nonce -- specifically so the whole
1,184-run grid is bit-reproducible across machines and re-runs. Production
deployment should use a fresh random >=128-bit nonce per image
(`secrets.token_bytes(16)`) instead; both conventions are documented together
in `payload.py` so the difference is never accidentally load-bearing.

## Limitations

See the paper's own Limitations subsection (`paper/IEEE_Paper.tex`, Section
"Comparison, Explainability, and Limitations") for the full, current list --
it is not duplicated here so it cannot drift out of sync with the paper.

### Measured, not adopted: per-channel block maps

`src/blockmap.py:228-232` binds no `channel` into the map seed, so one permutation
serves R, G and B. That means a holder block carries a partner's *complete colour*
descriptor, and recovery of a block is all-or-nothing. Binding channel instead would
give three independent permutations, so a block is only fully lost when all three of
its holders die. That was measured rather than argued about, over 21 image/severity
combinations with real embedding, real pen-stroke scribbles and real detection:

```
unrecoverable blocks, light scribble        100  ->  3     (98% fewer)
recovered PSNR, whole image, mean          +12.6 dB, worst +8.4 dB, 21/21 improved
cost of losing one channel to the fill      0.15 dB on a document,
                                            4.3 dB on saturated colour (kodim23)
```

It was **not adopted**, and the reasons are worth recording because two of them are
not obvious:

1. It loses to a far cheaper option on the aggregate number. Keeping the shared map
   and simply interpolating the magenta scores **+15.3 dB** mean against the same
   baseline -- 2.6 dB *better* than three maps, because the shared map already
   recovers ~86% of flagged blocks in full colour and the interpolator only has to
   cover the remainder, whereas three maps demote ~40% of blocks to a chroma
   estimate.
2. PSNR is measuring the wrong thing on documents, and the pictures disagree with it:
   interpolation erases glyphs, while a block rebuilt from a surviving channel keeps
   the real letter shape and only gets the hue wrong. On text, three maps look
   dramatically better than their score. On smooth photo content the reverse holds --
   the chroma estimate leaves visible pastel patches that interpolation does not.
3. It is the most invasive of the options. Recoverability is a *block*-level decision
   throughout: `detect.py:173` ORs the three channels into one mask before anything
   downstream sees them, and `recover.py:110-114` derives one `T`/`U`/`R` for all
   three. Per-channel recovery would need a tri-state model that `rho = 1 - |U|/|T|`
   has no vocabulary for, a new library column so existing records still recover
   correctly, and a re-run of the 1,184-row grid with every table and figure redrawn.

So the shipped answer is the cheap one, quarantined as described above, and the
honest route to a perfect file stays "restore exactly from library". The genuinely
better long-term fix is neither of these: erasure-coded reference sharing (k-of-n
descriptor shares instead of a 1:1 partner) degrades gracefully by construction
rather than patching the all-or-nothing case after the fact.
