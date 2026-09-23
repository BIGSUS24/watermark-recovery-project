# Fix Plan — 40 limitations, 6 architectural suggestions

Source: `limitations.md` (#1–#40), `improvements.md` (Fix-for-#N, S1–S6).

Roles: **Opus** plans, sequences, and reviews every phase gate. **Sonnet** writes the code and
the prose. No phase starts until the previous gate passes.

Rule applied throughout: a fix earns its place only if it repairs something real. Fourteen of the
proposed fixes are rejected below with reasons — rejection is part of the plan, not an omission.

---

## The sequencing constraint that drives everything

Three changes move every number in the paper:

- **#38** Variant C into the main grid (replacing B)
- **#40** RATIOS 3 values -> 7 values
- **#27** LSB shifting (+~2 dB watermarked PSNR)

The grid currently runs sequentially for hours (**#34**). Re-running it three times is the whole
budget. So:

1. Land **#34** (parallel runner) **before** anything that changes numbers.
2. Land every number-changing code fix **together**.
3. Re-run the grid **exactly once**.
4. Rewrite every document from that one run.

Any other order wastes hours or ships documents quoting three different grids.

---

## Phase A — code defects, no effect on published numbers

Three Sonnet agents, disjoint file sets, run in parallel.

### A1 · `webapp/` — Sonnet

| # | Fix | Where |
|---|---|---|
| 23 | Replace global `SESSION` dict with `flask.session` keyed per browser tab | `webapp/server.py:50` |
| 16 | Encrypt `key` column at rest: AES-256-GCM under `WATERMARK_MASTER_KEY` env var; refuse to start against a plaintext-key DB unless `--allow-plaintext-keys` | `webapp/db.py:41,85` |
| 39 | Soft-delete (`deleted_at` column), `/api/export` zip with `manifest.json`, `PRAGMA journal_mode=WAL` | `webapp/db.py:127,57` |
| 37 | Yellow banner when `map_info["relaxations"] > 0`; reject images under 128x128 | `webapp/server.py`, `src/blockmap.py` |
| 2,3 | Reject an upload whose shape differs from the stored row — one line, closes the resize/rotate hole at the app layer | `webapp/server.py` |
| 29 | Rename toggle to "Show cosmetic fill (no authentication — preview only)" | `webapp/static/` |

Not doing: the diagonal "NOT FOR EVIDENTIARY USE" overlay. The download endpoint already never
serves the filled image; a second warning on a file nobody can download is theatre.

### A2 · `src/` I/O and embedding — Sonnet

| # | Fix | Where |
|---|---|---|
| 30 | Parse the VP8/VP8L/VP8X chunk id; add `webp_lossless` to `LOSSLESS` | `src/imageio_any.py:63,28` |
| 24 | Route `embed.py` / `recover.py` input through `imageio_any` so RGBA composites instead of hard-rejecting | `src/embed.py`, `src/recover.py` |
| — | Add `flask==<pinned>` to `requirements.txt` — **in neither source document**; `webapp/server.py:38` imports it and the pinned-for-reproducibility file omits it | `requirements.txt` |

### A3 · `src/run_experiments.py` — Sonnet

| # | Fix | Detail |
|---|---|---|
| 34 | `ProcessPoolExecutor` + `--jobs N`. Cells are key-derived and deterministic — embarrassingly parallel. Embed cache computed once, shared. | ~20 lines |
| 36 | `--qualitative-image NAME`, default to a Kodak image, not `lena` | Lena's redistribution status is contested |
| 36 | `licence` column in `samples/manifest.csv` | |

**Gate A (Opus).** `python src/test_e2e.py`, `python src/sanity_gate.py`, every module self-check.
The parallel runner must produce a CSV **byte-identical** to the sequential one on `--quick` — if
determinism broke, the parallelism is wrong and nothing downstream is trustworthy.

---

## Phase B — the number-changing batch

One Sonnet agent, because these interact and must be measured together.

- **#27 LSB shifting.** Instead of overwriting the 2 LSBs, shift the pixel by ±1 when the carried
  bits already differ. Expected distortion drops from 1.5 to 0.5 LSB units, roughly +2 dB, closing
  most of the 2.4 dB gap to AuSR1's 45.57 dB. Must stay bit-exact on extraction — the gate is that
  `detect` recovers the identical payload on every corpus image.
- **#38** `VARIANTS = ("A", "C")` in the main grid; B demoted to an ablation-only block.
- **#40** `RATIOS = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70)`. Maps the collapse cliff between
  25% and 50% that three coarse points currently hide.
- **#32** Emit `n_refinement_flagged` into `runs.csv` and the web UI.

**#32's proposed logic change is deliberately NOT applied blind.** `improvements.md` says skip
recovery for any block whose own tag matched. But isolated-negative fill exists to close holes
inside a tampered region — and **#33** documents exactly the case where a tampered block passes its
tag anyway (a smooth inpainter reproducing the original MSBs). Skipping recovery there reopens the
hole the rule was written to close. So: measure both ways on the full grid, keep the one with
better in-region PSNR, report the loser in the paper. Opus decides on the numbers, not the prose.

**Gate B (Opus).** Watermarked PSNR moved up and payload extraction is still bit-exact, or LSB
shifting reverts.

---

## Phase C — one grid run

`python src/run_experiments.py --jobs 8` → `sanity_gate.py` → `make_tables.py` → `sync_paper_tables.py`.

Everything downstream quotes this run and nothing else.

---

## Phase D — documents, all from Phase C's numbers

Two Sonnet agents.

### D1 · `paper/IEEE_Paper.tex`, `paper/Synopsis.tex`

| # | Change |
|---|---|
| 25 | Reframe novelty: not "detect *and* recover" (EditGuard 2024, DeepMark 2026 do both) but **deterministic, training-free, cryptographically auditable**. Add a "Comparison to Learned Methods" subsection. |
| 31 | Demote block-level precision to a footnote naming it structurally vacuous under the `any` ground-truth rule; pixel precision (~0.95) becomes the headline localization number. |
| 28 | Cite Aminuddin et al. (2024) and state ρ = TCBR explicitly. One paragraph removes a priority dispute. |
| 8 | Baseline sub-table against Korus & Dziech (37 dB) and Wu et al. (>30 dB) at matched α, naming the 1-to-1 mapping as the cause. |
| 14 | State plainly that ~0.95 pixel precision is 8x8 quantization and cannot improve without a finer grid. |
| 15 | Explicit Threat Model section: adversary without the key; key compromise voids all guarantees. |
| 18 | Move the rejected quadrant-interleave, and its measured ~1.5-point ρ cost, from code comments into a security-analysis paragraph. |
| 35 | State the per-channel 32-bit posture explicitly; stop implying 96 bits per block. |
| 33 | Put `inpaint_removal` recall in the abstract, not buried in a table. Most realistic attack, weakest class. |
| 12 | Side-by-side crop figure: our 8x8 boundary against AuSR's 2x2, same region. Cheaper than hybrid blocks, same reviewer credit. |
| 13 | Table: false-accept probability against block size, showing tag size is independent of block size. The paper conflates them today. |
| 40 | Plot ρ(α) as a curve with the theoretical `1−α` overlay. The single figure that communicates the structural limit. |
| — | **RESOLVED — see "The Wu et al. citation" below.** The missing `\bibitem` now exists, and checking it against the source found three errors in our own Table II row. |
| — | 2 `PLACEHOLDER` in the paper, 9 in the synopsis. Paper is 15 pages against an IEEE norm of 6–8; synopsis 18 against an SPPU norm of 8–12. |

### D2 · `README.md`, new `DEPLOYMENT.md`, `ppt/`, proposal

- **#21,#22** `DEPLOYMENT.md`: every pipeline step marked SAFE or FATAL. EXIF strip and block-aligned
  lossless crop SAFE; JPEG conversion, CDN auto-optimisation, WhatsApp, Telegram FATAL.
- **#19** "Before You Deploy" checklist — pre-embedding is mandatory, legacy images cannot be covered.
- **#5** Replace the raw HTTP 400 on a lossy upload with a readable message.
- Carried over: README states the Variant C gain as +3.43/+2.52 dB, `src/payload.py` says
  +3.19/+2.33 dB. One is wrong. Resolve against Phase C output.

**Gate D (Opus).** A script greps every numeric claim in every document and diffs it against
`output/runs.csv`. A number absent from the CSV fails the gate. This is the check that prevents the
three-different-grids failure.

---

## The Wu et al. citation — resolved, and it was wrong three ways

`paper/IEEE_Paper.tex` cites "Wu et al. (CMC 2025)" five times (lines 248, 423, 427, 432) with no
`\bibitem`. The real reference:

```latex
\bibitem{wu2026multifeature} Q. Wu, H. Li, M. Li, and M. Wang, ``Multi-feature fragile image
watermarking algorithm for tampering blind-detection and content self-recovery,''
\emph{Computers, Materials \& Continua}, vol. 86, no. 1, pp. 1--20, 2026,
doi: 10.32604/cmc.2025.068220.
```

Verified against the published text. Three corrections to our Table II row (line 423), which
currently reads `Wu et al.\ (CMC 2025) & $>$41 & -- & $>$30 @ 50\% tamper & 0\% FPR/FNR, 100\% det...`:

1. **Year is 2026, not 2025.** Volume 86(1) is a 2026 issue; only the DOI carries 2025 (submission).
   All five in-text mentions say 2025.
2. **">30 @ 50% tamper" is real but not general.** Their Table 5: *"PSNR2 value of the recovered
   image under 50% tampering rate remains above 30.66 dB"* — that is the **copy-paste** attack
   specifically. Quoting it as an unqualified 50% figure overstates their result and therefore
   overstates our own gap.
3. **"0% FPR/FNR, 100% detection" is real but not general.** Their Table 7: *"FPR and FNR under
   three attack strengths all are 0, TDR values are 100%"* — **cropping** attack only. Table 9 gives
   FNR 0 / TDR 100% for JPEG, rotation and scaling. There is no universal claim. Their headline
   detection number is 94.09% average at 10% TR.

Useful for our own honesty table: **their scheme also collapses at extreme ratios** — 20.14 dB at
80% TR under noise addition, 16.75 dB at 80% under vector quantization (their Tables 8 and 9). With
#40 extending our grid to 70%, we can compare collapse curves rather than single points, which is a
fairer and more interesting comparison than the current one-number gap.

D1 must fix the year in all five mentions, qualify both numbers by attack type in the table caption,
and re-derive the gap claim from the qualified figures. **Table II is generated** — the row lives in
`src/make_tables.py` and is inlined into `paper/IEEE_Paper.tex:415`; edit the generator, not the tex.

### The other two baselines were checked the same way and are clean

- **Korus & Dziech (IEEE TIP 2013, vol. 22 no. 3, doi 10.1109/TIP.2012.2227769)** — "average
  reconstruction quality, measured on 10,000 natural images is 37 dB, and is achievable even when
  50% of the image area becomes tampered." Our row quotes this exactly. No change.
- **AuSR1 (Aminuddin & Ernawan 2022, J. King Saud Univ. CIS)** — 45.57 dB, SSIM **0.9972**,
  tamper-detection precision 0.9943, 2x2 blocks, 2 LSBs, LSB shifting. Our row is right; it rounds
  SSIM to "≈0.99" when the published figure is 0.9972. Use the real number.

One in three cited rows was wrong. That is the argument for the Gate D numeric check covering
*cited* numbers too, not only our own measured ones.

---

## Phase E — optional, user decides

**S1 · Fountain codes (#8, #9, #10).** Replace the 1-to-1 partner mapping with an LT/Raptor code
over block descriptors. Any k surviving blocks recover all n. The only fix that closes the 20 dB gap
at 50% tamper, and it removes the `ρ → 1−α` collapse instead of documenting it.

Also the only item here that is a publishable contribution rather than a repair. Very high effort.
**Say the word and it becomes Phase E; otherwise the paper reports the gap honestly and names
fountain codes as future work.**

---

## Rejected, with reasons

| # | Proposed | Why not |
|---|---|---|
| S2 | Learned autoencoder Variant D | Contradicts the project. #25 concludes the *only* defensible novelty left is "deterministic, training-free". A trained descriptor spends exactly that. |
| S3 | FastAPI + React SPA rewrite | Nobody asked. The Flask app works. |
| S6 | Public Hugging Face demo | Not a capstone deliverable. |
| S5 | DICOM demo | Good story, new dependency, no real PACS to test against. Reopen if the guide wants it. |
| 1 | Semi-fragile / DCT mid-band mode | A different scheme. Fragile-by-design *is* the threat model; softening it invalidates every result. Document instead. |
| 4 | Bit-tolerance, wider MSB window | Trades authentication strength for benign-edit tolerance nobody requested. |
| 12,13 | Hybrid 2x2 detection, two-tier payload | Real research, not a fix. The comparison figure buys the same reviewer credit in an afternoon. |
| 15 | Hardware key binding, RFC 3161 timestamping | Deployment engineering for a system with no deployment. The threat-model section covers the honesty requirement. |
| 19 | Passive perceptual-hash companion | A second, unrelated system. |
| 20 | Histogram-shifting reversible mode | High effort. An `--export-lsb-backup` sidecar gives reversibility in ~15 lines if wanted. |
| 10,11 | Inpainting fallback for unrecoverable blocks | **Already shipped** as the cosmetic-fill toggle, correctly quarantined from every metric. Making it a default would undo that. |
| 9 | Re-add quadrant interleave | Removed for a measured structural leak. Re-adding it to chase 1.5 points of ρ trades a security property for a metric. |
| 29 | Evidentiary-use overlay on downloads | The filled image is never downloadable. |
| 6,7 | Variant D larger descriptor budget | Superseded by S1, which fixes the cause instead of the symptom. |

---

## Counts

- 40 limitations: **26 fixed**, 14 rejected with reasons (11 documented rather than coded).
- 6 architectural: 0 taken, S1 offered as an explicit decision.
- 1 defect found outside both documents (`flask` unpinned).
