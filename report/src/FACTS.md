# FROZEN FACT SHEET — Watermark-Guided Tamper Localization and Recovery
# B.E. Project Work-I report, ADYPSOE / SPPU, AY 2026-27.
# EVERY number you write MUST come from this file. Do not invent, round differently,
# or copy numbers out of paper/Synopsis.tex (some of its prose numbers are stale).

## Title
Watermark-Guided Tamper Localization and Recovery:
A Key-Seeded Self-Embedding Fragile Watermarking Scheme with Joint Localization
and Restoration Assessment

## One-line description
A deterministic, training-free self-embedding fragile watermarking scheme. Each
8x8 block of the image carries, in its two least-significant bit-planes, a 32-bit
keyed HMAC-SHA256 authentication tag over its own six most-significant bit-planes
plus a 96-bit compressed recovery descriptor of a spatially distant partner block
chosen by a key-seeded single-cycle permutation. Verification recomputes the tag;
a mismatch localizes tampering at block granularity; a flagged block is rebuilt
from the descriptor its surviving partner carries, or explicitly marked
unrecoverable rather than fabricated.

## Design constants
- Block size B = 8 (main), B = 4 (ablation).
- Capacity cap(B) = 2B^2 bits per block per channel = 128 bits at B = 8.
- Split: tag t(B) = min(32, cap/2) = 32 bits; descriptor d(B) = 96 bits.
- MSB projection: msb(a) = a AND 0xFC (zeroes the two LSBs, idempotent).
- Tag: a_i = Trunc_32( HMAC-SHA256_Ks( ID || i || MSB(b_i) || r_{m^-1(i)} ) ).
- Block map m: bijective, single K-cycle, min separation d_min = 0.25*min(M,N).
- Descriptor Variant A: level-shifted orthonormal 2-D DCT, first 12 zig-zag
  coefficients, each quantized to a signed 8-bit value with JPEG quality-50
  luminance step sizes = 12 x 8 = 96 bits exactly.
- Descriptor Variant B (ablation): 4x4 array of 2x2 block means at 6 bits each.
- Descriptor Variant C (main default): adaptive/rate-distortion-fitted DCT.
- Recoverability rate rho = 1 - |U| / |T|, where T is the flagged set and
  U = { i in T : m(i) in T }. Structural bound E[rho] approx = 1 - alpha.
- LSB shifting (not replacement): a descriptor-carrying pixel is moved to the
  nearest value whose low bits already match; tag-carrying pixels are never
  shifted. Mean distortion approx 0.5 LSB instead of approx 1.5 LSB.
- Complexity: one keyed hash and one BxB transform per block, O(MN) overall.
  No iteration, no optimization, no training. Problem class P.

## Corpus and evaluation grid (frozen)
- Corpus: 32 colour images = 8 USC-SIPI (512x512) + 24 Kodak. Every file pinned
  by SHA-256 so the corpus reproduces byte for byte.
- Total grid: 3,232 rows in output/runs.csv.
  - Main grid: 1,792 rows = 32 images x 4 tamper classes x 7 ratios x 2 variants (A, C), B = 8.
  - Null condition: 320 rows = 32 images x 2 variants x 5 keys.
  - Ablation: 1,120 rows (block-size ablation at B = 4, and a Variant-B ablation).
- Tamper classes (4): copy-paste splicing; object removal by inpainting;
  crop-and-refill; noise corruption.
- Tamper ratios (7, nominal): 0.10 0.20 0.30 0.40 0.50 0.60 0.70.
- Achieved ratio at nominal 0.70 is 0.653; at 0.60 it is 0.573. The region
  generator cannot reliably place one compact region over 60-70% of a frame, so
  the two highest ratios are nominal only. All lower ratios match within 0.005.
- Automated sanity gate: 25 of 27 checks pass. The 2 soft warnings are the
  inpainting MSB-preserved-miss category and 3 rows with slightly elevated
  coincidentally-unchanged pixels. No table or figure is emitted unless the gate runs.

## Measured results (frozen — quote exactly these)
### Imperceptibility (32-image corpus, B = 8, LSB shifting)
- Variant A: mean PSNR 45.479 dB, mean SSIM 0.98847.
- Variant C: mean PSNR 45.492 dB, mean SSIM 0.98841.
- Minimum SSIM observed over the whole B = 8 set: 0.97831.
- Per-image PSNR-A: Airplane 45.72, Baboon 45.70, House 45.71, Lena 45.73,
  Pepper 45.64, Sailboat 45.71, Splash 45.66, Tiffany 44.07.

### Localization (main grid, 1,792 trials)
- Block-level precision 1.0000 (structurally forced by the ground-truth rule —
  a block counts as tampered if the region covers any of its pixels — so it is
  NOT evidence of detector quality and must not be headlined).
- Block-level recall 1.0000 for splicing, crop-and-refill and noise corruption;
  0.99998 for object removal by inpainting.
- 17 MSB-preserved-miss blocks in total across the main grid; these are the
  predicted residual of the descriptor-binding design, appearing in measurement.
- Pixel-level precision 0.9599 (main-grid mean). Its shortfall from 1.0 is the
  8x8 block-quantization penalty and cannot improve without a finer grid.
- Pixel precision rises with tamper ratio: 0.9248 (0.10), 0.9481 (0.20),
  0.9581 (0.30), 0.9643 (0.40), 0.9701 (0.50), 0.9740 (0.60), 0.9797 (0.70).
- Neighbourhood refinement flagged only 2 blocks out of 10,092,544 verified.

### Null condition (unmodified watermarked images)
- 320 rows, 1,802,240 independent block verifications, 0 false-positive blocks.
- Block-level false-positive rate 0.000000; rule-of-three 95% upper bound 1.66e-6.
- This is a determinism and implementation-consistency check across images,
  variants and keys. It is NOT a measurement of the 2^-32 cryptographic
  false-accept probability. Say so.

### Recovery (main grid)
- rho by nominal alpha: 0.9590 (0.10), 0.8584 (0.20), 0.7479 (0.30),
  0.6371 (0.40), 0.5335 (0.50), 0.4437 (0.60), 0.3579 (0.70).
- Structural bound 1-alpha: 0.90 0.80 0.70 0.60 0.50 0.40 0.30.
  rho sits 3-6 percentage points ABOVE its bound at every ratio; monotone,
  near-linear, no collapse.
- Mean rho over the main grid: 0.6482.
- In-region recovery PSNR: Variant A 28.49 dB, Variant C 31.13 dB,
  main-grid mean 29.81 dB. Essentially FLAT across the whole ratio range.
- In-region SSIM: Variant A 0.5009, Variant C 0.5523.
- Whole-image PSNR under the unmarked convention falls with coverage:
  Variant A 21.40 dB mean; at 50% tamper it is 17.39 dB; the honest marked
  output at 50% is 12.40 dB.
- Interpretation: mapping COVERAGE, not descriptor fidelity, is the dominant
  constraint on recovery quality. Reference sharing is the identified upgrade.

### Block-size ablation (B = 8 vs B = 4)
- Pixel precision 0.9599 -> 0.9794 (finer localization).
- In-region PSNR 29.63 dB -> 26.78 dB (2.85 dB lost).
- Per-block payload falls 128 -> 32 bits; tag halves 32 -> 16 bits, so the
  per-block false-accept probability rises from 2^-32 to 2^-16, which on a
  512x512 image with 16,384 blocks is an expected approx 0.25 false accepts per
  image. Report this as an honest finding.

### Comparison with published schemes (their figures are cited, not re-implemented)
- AuSR1 (Aminuddin & Ernawan 2022): WM PSNR 45.57 dB, SSIM approx 0.99,
  recovered 27.64 dB worst case, 2x2 blocks.
- Wu et al. (CMC 2025): WM PSNR > 41 dB, recovered > 30 dB at 50% tamper,
  0% FPR/FNR.
- Korus & Dziech (IEEE TIP 2013): recovered 37 dB at 50% damage, fountain codes.
- Ours (Variant A, measured): WM PSNR 45.48 dB, SSIM 0.9885, recovered 17.39 dB
  at 50% tamper under the unmarked convention (12.40 dB for the honest marked
  output), block precision 1.0000, block recall 1.0000, pixel precision 0.9599.

### Measured runtime (512x512x3, commodity AMD x86-64 CPU, single thread, Python)
- Embedding 473 ms; verification 197 ms. No GPU at any stage.

## Software stack
Python 3.10+; NumPy 2.1.2; OpenCV-headless 5.0.0.93; scikit-image 0.26.0;
Pillow 10.4.0; Flask (web application); Streamlit 1.61.1 (demonstration
interface); Matplotlib 3.11.1 (figures); SQLite (local protected-image library);
hashlib / hmac / struct from the standard library — no third-party cryptography,
no machine-learning framework, no trained parameters.
Codebase: 9,929 non-comment, non-blank lines of Python across 24 modules.

## Database (SQLite, webapp/library.db) — single table `protected`
id INTEGER PK AUTOINCREMENT; name TEXT NOT NULL; created_at TEXT NOT NULL;
height INTEGER NOT NULL; width INTEGER NOT NULL; block INTEGER NOT NULL;
variant TEXT NOT NULL; key TEXT NOT NULL; image_id BLOB NOT NULL; png BLOB NOT NULL;
sha256 TEXT NOT NULL; psnr REAL; ssim REAL; blocks INTEGER; deleted_at TEXT;
key_encrypted INTEGER NOT NULL DEFAULT 0.
Indexes: idx_shape (height, width, block); idx_sha (sha256).

## Modules (src/)
payload.py (key derivation, bit budget, geometry, MSB projection, tag, descriptor
encode/decode, LSB packing); blockmap.py (key-seeded single-cycle permutation,
minimum-separation repair, R1-R3 verification); embed.py; detect.py (extract,
recompute, block mask, refinement, pixel mask, per-block audit record);
recover.py (split flagged set into recoverable/unrecoverable, rebuild, mark,
report rho); tamper.py (four tamper classes with exact ground-truth masks);
metrics.py; run_experiments.py; sanity_gate.py; make_tables.py; plots.py;
fountain.py (Variant D exploration); fit_variant_c.py; imageio_any.py;
test_e2e.py. Applications: webapp/server.py + webapp/db.py (Flask + SQLite);
demo/app.py (Streamlit).

## Scope
IN: still images, greyscale and 3-channel colour, 8 bits/channel, lossless
containers (PNG, BMP, TIFF). Block sizes 8 and 4. Descriptor variants A, B, C.
Four tamper classes at seven ratios. 32-image corpus. A local web application
and a demonstration interface over the same pipeline.
OUT: video and audio; robustness to lossy re-encoding, resizing, rotation or
filtering (the scheme is fully fragile by design); adversaries holding the secret
key; real-time embedding in camera firmware; competing with learned detectors on
their own accuracy terms.

## The research gap (state it precisely — do not overclaim)
NOT claimed: the distant-mapping idea (that is AuSR3's, Aminuddin & Ernawan 2023).
NOT claimed: superiority over learned proactive watermarking such as EditGuard,
which already localizes and recovers.
The contribution is threefold:
1. Determinism and auditability — every positive detection reduces to one
   recomputed keyed hash comparison that any third party holding the key can
   repeat bit for bit; no training data, no GPU, no run-to-run variance.
2. An explicit keyed construction in which every bound field is stated and
   analysed together with the specific attack it defeats.
3. Joint evaluation — imperceptibility, localization and recovery reported
   together, with the recoverability rate and the unrecoverable fraction
   disclosed rather than excluded, across four tamper classes and seven ratios
   against exact ground-truth masks.
Additional construction detail that IS ours: the permutation is built directly in
cycle notation from a cryptographically seeded Fisher-Yates shuffle, so
bijectivity and the absence of fixed points and short cycles hold by
construction rather than by rejection sampling, with an enforced
minimum-separation repair pass.

## Known limitations (be honest, the examiners value this)
- Fully fragile: any lossy re-encode, resize or filter destroys the watermark.
  The scheme protects images inside a lossless custody chain, nothing else.
- One-to-one backup allocation fails all-or-nothing per block. Reference-sharing
  and fountain-coded schemes degrade more gracefully and reach far higher
  whole-image reconstruction at high tamper ratios.
- Recovery is a low-frequency approximation (12 DCT coefficients), not the
  original block.
- Pixel-level precision is capped by block quantization at 0.9599 for B = 8.
- The two highest tamper ratios are nominal only (achieved 0.573 and 0.653).
- At B = 4 the tag halves to 16 bits, raising the false-accept probability to
  2^-16.
- Security rests on key secrecy; an adversary holding the key can re-embed.
- Capacity is fixed: the two LSB planes of a 512x512 colour image hold
  1,572,864 bits (4,096 blocks x 128 bits x 3 channels) = 192 KB.

## Applications
Forensic evidence archives; media authentication at ingest; medical imaging
integrity in PACS; legal and official document scans; insurance claim
verification; self-authenticating camera or scanner firmware. All share the
property that makes an active scheme viable: an acquisition pipeline under
institutional control.

## Future work
1. Reference sharing / fountain-coded descriptor allocation (the highest-value
   upgrade, identified directly by the coverage-dominates finding).
2. A semi-fragile mode tolerant of benign JPEG re-encoding.
3. Finer or hierarchical localization grids without paying the full tag cost.
4. Integration into capture firmware and PACS/DICOM ingest.
5. Formal security proof of the keyed construction.

## Project team and institution
Department of Computer Engineering, Ajeenkya DY Patil School of Engineering,
Charholi Budruk, Lohegaon, Pune 412105. Savitribai Phule Pune University.
Academic year 2026-27. Guide and student names are placeholders in the report.
