# Implementation Plan — Watermark-Guided Tamper Localization and Recovery

**Date:** 11 August 2026
**Status:** Zero implementation code exists. This document is the complete build plan.
**Produced by:** three independent planning agents (core algorithms / evaluation harness / demo + sequencing), merged and reconciled.

---

## 0. What we are building

A complete, working watermarking system — not a demo, not a prototype. Concretely:

1. A Python implementation that embeds a self-authenticating watermark into an image, detects and localizes tampering, and recovers damaged content.
2. A tamper-simulation harness with exact ground truth across 4 attack classes.
3. An evaluation run of **1,184 configurations** producing real measured numbers.
4. A sanity gate that fails loudly if those numbers fall outside literature-validated ranges.
5. LaTeX tables and figures generated directly from the results — never hand-typed.
6. A Streamlit interface, built last, on top of already-verified code.

The Python core is the sole authoritative implementation. Every number in the paper comes from it.

---

## 1. Verified environment

```
python 3.12.5     numpy 2.1.2      opencv 5.0.0     scikit-image 0.26.0
pillow 10.4.0     streamlit 1.61.1  pandas 3.0.5     scipy 1.18.0
hmac / hashlib / csv / struct / secrets: stdlib
matplotlib: MISSING          scikit-learn: MISSING
```

**Decisions this forces:**

- **CSV handling: stdlib `csv` + `statistics`, not pandas.** 1,184 rows is not a pandas problem, and pandas 3.x is new enough that its API surface is a reproducibility risk we gain nothing from taking. Pandas remains available if aggregation ever gets genuinely awkward.
- **Figures: install matplotlib** (`pip install matplotlib`). This is the one place to break the no-new-dependency rule. A hand-rolled Pillow chart is ~80 lines to produce something that looks amateur in an IEEE paper; matplotlib is one install for publication-quality output. The dependency earns it.
- **Refinement convolution: hand-rolled 3×3 slice sum, not `scipy.ndimage`.** We need explicit control of the border constant and a per-cell valid-neighbour count (see §4.3). Four lines, exact control.
- **SSIM parameters must be pinned explicitly.** scikit-image 0.26 removed `multichannel` in favour of `channel_axis`, and `data_range` must be passed rather than dtype-inferred. Unstated defaults are a reproducibility hole.

---

## 2. File layout

```
watermark-recovery-project/
  src/
    payload.py           conventions, key derivation, MSB projection, HMAC tag, descriptors, bit packing
    blockmap.py          key-seeded single-cycle permutation + inverse + R1/R2/R3 verification
    embed.py             embedding pipeline, image_metrics (the ONE PSNR/SSIM implementation)
    detect.py            tag recomputation, refinement, mask expansion, descriptor snapshot
    recover.py           inverse lookup, reconstruction, unrecoverable marking, rho
    tamper.py            4 tamper classes with exact seeded ground truth
    metrics.py           confusion matrix, in-region recovery metrics, CSV/aggregation helpers
    run_experiments.py   the 1,184-run grid -> output/runs.csv
    plots.py             figures
    make_tables.py       runs.csv -> LaTeX table bodies
    sanity_gate.py       hard/soft threshold checks against literature bands
    test_e2e.py          keystone assertion + golden vectors + tamper smoke
  samples/
    fetch_corpus.py      corpus download, standardize to PNG, SHA-256 pin
    manifest.csv         generated: filename, dims, sha256, source, fetch time
    usc_sipi/  kodak/
  demo/
    app.py               streamlit run demo/app.py
  output/
    runs.csv  sanity_gate_report.txt  images/  figures/  tables/
  paper/ ppt/
  README.md  requirements.txt
  RESEARCH-FINDINGS.md  IMPLEMENTATION-PLAN.md  EXPLAIN-SIMPLE.txt
```

No `__init__.py`, no `utils.py`, no `config.py`, no class hierarchies. Two `NamedTuple`s total. Dependency graph is a DAG: `payload` ← `blockmap` ← `embed`/`detect` ← `recover`.

**`demo/app.py`, not `src/app.py`** — deliberately, so `grep -rl streamlit src/` returns nothing. That makes "every paper number comes from `src/` with no UI dependency" mechanically checkable rather than a promise.

**`requirements.txt` pins exact versions** (`pip freeze` immediately before the run that produces the paper's final numbers, committed alongside `runs.csv`). Reproducibility is a claimed contribution; a loose `>=` range would quietly undercut it.

---

## 3. Shared conventions

These live at the top of `src/payload.py`. Everything imports them.

| Thing | Convention |
|---|---|
| Images | `np.uint8`, `0..255`. Greyscale `(H,W)`; colour `(H,W,3)` **RGB** |
| Channel order | RGB internally, always. OpenCV BGR converted at the I/O boundary only |
| Block stacks | `(K, B, B)` uint8, raster block-row-major order |
| Bit arrays | `np.uint8` holding only 0 or 1 — never `bool` |
| Bit order | **MSB-first / big-endian everywhere.** `np.unpackbits` default, `to_bytes(...,'big')`, `struct` `>` prefix |
| Block indices | **0-based in code** (paper's 1-based notation is cosmetic; must be stated in the paper) |
| Intermediate arithmetic | DCT in `float64`. Anything that can exceed 255 casts to `int16` **first** — NumPy 2 wraps `uint8 * int` silently |
| Variant | literal string `"A"` or `"B"` |
| Output files | Lossless only. `save_image()` asserts extension in `{.png,.bmp,.tif,.tiff}` |

### 3.1 Key derivation

```python
KEY_LABEL_TAG = b"wgtlr/v1/tag"
KEY_LABEL_MAP = b"wgtlr/v1/map"

def coerce_key(key: bytes | str) -> bytes: ...
def subkey(key: bytes, label: bytes) -> bytes:
    return hmac.new(coerce_key(key), label, hashlib.sha256).digest()
```

Two domain-separated subkeys only. A weakness in the mapping (structurally guessable) cannot leak tag-forging material. The `v1` version prefix means any future serialization change fails loudly instead of verifying wrongly.

### 3.2 Image identifier — and its security consequence

**`ID` is caller-supplied opaque bytes, stored as side information. NEVER derived from pixel content.** A content-derived ID is self-defeating: tampering changes content, so the verifier would derive a different ID and every block would fail.

The tag binds `(ID, i, MSB(block))`. Index binding defeats *intra-image* transplant (Holliman–Memon collage). ID binding defeats *cross-image* transplant.

**Consequence that must appear in the paper:** if `ID` is reused across images, cross-image transplant is possible for blocks at the same index. Production deployment requires a fresh random ≥128-bit nonce per image (`secrets.token_bytes(16)`). Research runs use a deterministic `stem|HxW|B` form so the whole grid stays bit-reproducible. Document both; use the deterministic one; note the nonce is the production choice.

Independently, geometry (`M, N, B, channel, variant`) is always bound into the HMAC message, so geometry confusion, block-size confusion, cross-channel transplant, and variant confusion are impossible regardless of what `ID` the caller chose.

### 3.3 Payload budget as a function of block size

The 128-bit split is **not** portable to `B=4` (capacity there is 32 bits, which the tag alone would consume). So it is derived:

```python
def budget(block: int) -> tuple[int, int, int]:
    cap = 2 * block * block
    tag = min(32, cap // 2)
    return cap, tag, cap - tag
```

| B | capacity | tag bits | desc bits | per-block false accept |
|---|---|---|---|---|
| 4 | 32 | 16 | 16 | 2⁻¹⁶ ≈ 1.5e-5 |
| 8 | 128 | **32** | **96** | 2⁻³² ≈ 2.3e-10 |

At `B=4` on 512×512 there are 16,384 blocks, so expected false accepts ≈ **0.25 per image**. That is the honest cost of the ablation — finer localization, materially weaker per-block authentication — and it is a real finding to report, not a defect to hide.

---

## 4. Core modules

### 4.1 `blockmap.py` — the highest-risk module, and how it got de-risked

Three independent reviewers flagged this as the main bug risk. One insight removes most of that risk:

> **Any permutation expressed in cycle notation is automatically a single K-cycle.** Given any arrangement `order` of `0..K-1`, defining `m[order[t]] = order[(t+1) % K]` yields a bijection (R1) that is one cycle of length exactly K (R3) — unconditionally, for every possible `order`. No fixed points, no mutual pairs, no short cycles, nothing to check or repair.
>
> **Corollary:** R2 repair may permute `order` freely — every rearrangement preserves R1 and R3. So the hard constraints are structural and only the soft geometric constraint needs search.

This is why shuffling the *mapping array* fails while shuffling the *cycle order* succeeds.

**API:**
```python
def build_map(key, image_id, shape, block, d_min=None) -> tuple[np.ndarray, np.ndarray, dict]
def block_centroids(shape, block) -> np.ndarray
def verify_map(m, centroids, d_min) -> dict
```

**Direction contract — pin this at the top of the file and repeat it in every docstring that touches the map:**
- `m[i]` = index of the block that **stores** block `i`'s descriptor
- `minv[i]` = index of the block whose descriptor is **stored in** block `i`

Every recovery bug in this class of scheme is an `m`/`minv` swap.

**Construction:**

1. **Deterministic keystream, not `random.Random`.** HMAC-SHA256 in counter mode. MT19937's shuffle is not spec-guaranteed stable across CPython releases, and this project promises bit-reproducibility. Six lines buys version-, platform-, and NumPy-independent determinism.
2. **Quadrant-interleaved seed order.** Split blocks by grid quadrant, shuffle each independently, interleave as Q0, Q3, Q1, Q2 (diagonally opposite adjacent). A flat shuffle on a 64×64 block grid violates `d_min=16` on roughly a third of its edges; the interleave violates only near-centre pairs, so repair converges fast.
3. **Monotone R2 repair by swapping elements of `order`.** Cost is a non-negative integer that only decreases, so the loop provably terminates. Each trial recomputes only the ≤4 affected edges — `O(1)` per trial, milliseconds even at K=16,384.
4. **Bounded relaxation, not silent failure.** If `d_min` is geometrically infeasible, halve it (max 4 times) and report `d_min_achieved`. Every corpus geometry meets `d_min` unrelaxed; the mechanism exists so the demo cannot crash on a 48×48 upload.
5. **Cycle notation → mapping:** `m[order] = np.roll(order, -1)`.

**Rejected: LCG `m(i) = (k·i + t) mod K`.** Bijective but its cycle structure is determined by gcd-arithmetic on `K` (always a power of 2 here, so routinely many short cycles), gives no control over R2, and is trivially invertible from two known pairs — exactly the weakly-keyed mapping the arXiv:1812.11735 attack exploits.

**Verification (called inside `build_map`, so a broken map cannot escape):**

| Req | Check |
|---|---|
| R1 bijective | `np.array_equal(np.sort(m), np.arange(K))` |
| R3 single K-cycle | Walk from 0; assert return to 0 after exactly K steps **and** K distinct indices visited. Subsumes no-fixed-points and no-2-cycles for K≥3 |
| R2 separation | `min(norm(cen - cen[m])) >= d_min_achieved - 1e-9` |
| inverse | `m[minv] == arange(K)` **and** `minv[m] == arange(K)` — both directions, since one alone passes for an involution |

**Edge cases:** `K < 3` → `ValueError` (R3 mathematically unsatisfiable). Non-square grids (Kodak 512×768) → quadrant split on block-grid dims, drain unequal lists in round-robin. `d_min` > image diagonal → relax and report.

**Self-check:** all 5 corpus geometries × R1/R2/R3/inverse; determinism across two calls and a subprocess; one-bit key change moves >99% of blocks; different `ID` gives a different map.

**Effort: 1.0 day.**

### 4.2 `payload.py` — projection, tag, descriptors, bit packing

**Bit-packing layout, pinned exactly.** Payload bit index `t ∈ 0..127`, pixel `p = t // 2` in raster order within the block:

```
payload_bits[i] = concat(tag_bits[i], desc_bits[minv[i]])
pair[p]         = 2 * payload_bits[2p] + payload_bits[2p+1]      # earlier bit -> higher weight
pixel           = msb_pixel | pair[p]
```

Vectorized: `pairs = 2 * bits[:, 0::2] + bits[:, 1::2]`.

**No overflow is possible:** `MSB(x) ≤ 252` and `pair ≤ 3`, so the OR is ≤ 255. The embedder needs no clip — worth stating in the paper, since it is why embedding is exactly invertible on the MSB plane.

**HMAC message serialization** — fixed-width and length-prefixed, no concatenation ambiguity:

```python
msg = (struct.pack(">4sHHHBBI", b"WGT1", M, N, block, channel, VARIANT_CODE[variant], i)
       + len(image_id).to_bytes(2, "big") + image_id
       + blocks_msb[i].tobytes())
a_i = hmac.digest(K_tag, msg, "sha256")[:tag_bits // 8]
```

The length prefix on `image_id` is not optional: without it, `ID=b"AB", i=1` could collide with `ID=b"A", i=...`. Textbook mistake.

Use `hmac.digest(...)` (one-shot) rather than `hmac.new(...).digest()` — roughly 3× faster in CPython, and K is 4,096–16,384 per channel.

#### A required paper correction, found while planning

`IEEE_Paper.tex:105` states `L=10` retained coefficients with `n_1=8` bits for DC "decreasing for AC terms" and `Σn_ℓ = 96`. **These three claims cannot all hold** — 10 coefficients starting at 8 bits and decreasing sum to well under 96.

**Resolution: uniform 8-bit signed fields with per-band step sizes.** `n_coef = desc_bits // 8` coefficients, each `int8`. For B=8 that is exactly **12 × 8 = 96 bits**; for B=4, **2 × 8 = 16 bits**.

Why uniform rather than ragged: 12 `int8` values are exactly 12 bytes, so packing is `arr.view(np.uint8)` → `np.unpackbits`. A ragged `[12,11,11,10,...]` allocation needs hand-rolled variable-width bit fields — the single most reliable source of off-by-one bugs in this project — for zero measurable fidelity gain. The decreasing-precision intent is preserved through the **step sizes** `Δ_ℓ` instead: an increasing `Δ_ℓ` is an effective decreasing allocation.

```python
# JPEG-50 luminance quantization table in zig-zag order, DC entry replaced by 8
DELTA_ZZ = np.array([8,11,12,14,12,10,16,14,13,14,18,17,16,19,24,40], dtype=np.float64)
```

**Provable no-clipping property** (state it in the paper — examiners like provable bounds): with an orthonormal DCT, Cauchy–Schwarz gives `|C(u,v)| ≤ 128B`. For B=8 that is 1024. DC step 8 → `1024/8 = 128` exactly fills `int8`; every AC step is ≥10 → `1024/10 = 102.4 < 127`. **No retained coefficient can ever clip, for any 8-bit input.** The `clip()` is therefore purely defensive, and the self-check asserts it never fires.

**Variant A:** level-shift by −128, orthonormal DCT via explicit matrix (`D @ X @ D.T` — one broadcast matmul over the whole stack, block-size generic, exact one-line inverse, no OpenCV in the numerics), zig-zag select `n_coef`, quantize with `np.rint` (round-half-even, **not** truncation, which would bias every coefficient toward zero and cost ~1 dB), pack via `int8` byte view. Two's complement round-trips for free through the byte view — that is the sign-handling decision: no sign-magnitude, no offset binary, no explicit sign bit, no bug.

**Variant B:** `G = B//2` mean-pool (exact — pixels are multiples of 4), quantize to `bits_per = desc_bits // (G*G)` bits, reconstruct at bucket midpoint. **`.astype(np.int16)` before the left shift is mandatory** — `uint8(63) << 2` wraps in NumPy 2.

Both decoders mask output with `& 0xFC`, so a recovered region deterministically fails re-authentication (a paper requirement) and the reconstruction target matches `MSB(original)` exactly.

**Two asserts that structurally prevent the worst bug in the project:** `encode_descriptor` and `block_tags` take parameters *named* `blocks_msb` and assert `np.all(blocks_msb & 0x03 == 0)` at entry. Keep them in production, not behind a debug flag.

**Dimensions not divisible by block: crop, do not pad.** Padding puts real blocks' descriptors into phantom blocks that get discarded, making those blocks unrecoverable by construction — a correctness hole, not a shortcut. Every corpus image is already a multiple of 8 and 4, so this never fires on results. **Second required paper edit:** §Notation says "symmetrically padded"; change to "cropped to the largest block-aligned region, with the crop reported."

**Effort: 1.0 day.**

### 4.3 `embed.py`

```python
def embed_image(img, key, image_id, block=8, variant="A", d_min=None) -> tuple[np.ndarray, dict]
def image_metrics(a, b) -> tuple[float, float]      # the ONE PSNR/SSIM in the project
```

**The one line that matters:**
```python
payload = np.concatenate([tags, desc[minv]], axis=1)     # minv, NOT m
```
Block `i` carries its own tag and the descriptor of block `minv[i]`. Equivalently, `desc[j]` lands in block `m[j]`. Both statements go in a comment on that line — it is the only place in the codebase where the direction is chosen. Using a fancy-index rather than a loop keeps the direction a single reviewable expression.

**Colour: each channel gets its own full payload** (own tags, own descriptors) — not a payload split across channels. Each channel's descriptor reconstructs its own content, capacity is 3× for free, and PSNR is unchanged since every channel takes identical 2-LSB distortion.

**Mapping is shared across all channels.** Binding `channel` into the map seed would give three different maps, letting a block be recoverable in R but not G — producing colour-fringed recovered blocks and three separate unrecoverable masks. One map, one mask, no fringing.

**Assert inside the function:** `np.array_equal(msb(wm), msb(img_cropped))` — the embedder must not disturb one MSB bit.

**The self-check's PSNR band is `42.0 <= psnr <= 44.16`, and the upper bound is the valuable half.** 44.15 dB is the analytical maximum for full-entropy 2-LSB embedding. A measured PSNR *above* it means the payload is not full-entropy — classic causes being an all-zero descriptor array, a `minv` indexing mistake producing a constant, or a `variant` typo falling through. A lower-bound-only assert passes on all of those.

Caveat that must be honoured or the check is flaky: the band is valid only for content with high-entropy low-frequency DCT. On a flat image the descriptor is genuinely near-zero and PSNR legitimately reaches ~50 dB. Hence `_synthetic_natural()` — deterministic gradient + sinusoid + seeded noise, ~4 lines, no corpus dependency.

**Effort: 0.5 day.**

### 4.4 `detect.py`

```python
class DetectResult(NamedTuple):
    raw_mask, block_mask, pixel_mask, desc_by_owner, per_channel, m, info
```

Returning **both** `raw_mask` (pre-refinement) and `block_mask` (post-refinement) satisfies the demo's staged-reveal requirement and the evaluation harness's need to report both — the isolated-positive rule costs recall on scattered tampers, and reporting only the flattering mask would violate the project's own reporting-discipline claim.

**The reindex derivation, spelled out because it is the bug to avoid.** `stored_desc[h]` is the descriptor found *inside* block `h`; embedding put `desc[minv[h]]` there, so it is the descriptor *of* block `minv[h]`. With `j = minv[h]`, so `h = m[j]`:

```
desc_by_owner[j] = stored_desc[m[j]]     ==>     desc_by_owner = stored_desc[m]
```

**`m`, not `minv`.** Detect uses `m` to read; embed uses `minv` to write. Put that sentence in the docstring.

**Why detect returns the descriptors at all:** so `recover()` never touches image LSBs. This is what makes the ordering bug structurally impossible rather than merely avoided (see §4.5).

#### Third required paper correction — border refinement

The paper's `τ=7` fixed threshold means a **corner block can never be filled** by refinement: it has only 3 real neighbours, so `S ≤ 3 < 7`. Border blocks would be silently exempt from the fill rule.

Fix: scale the threshold by the valid-neighbour count, `thresh = ⌈τ·|N(i)|/8⌉`. Keeps the rule proportionally identical (τ/8 = 0.875 → corner needs 3 of 3, edge needs 5 of 5) for two extra lines. **Paper edit:** note this in §Tamper Detection.

**The isolated-positive rule is a genuine false-negative source and must not be hidden.** A single-block tamper has `S=0` and gets cleared, so it is missed entirely. That is why both masks are returned, and why the scattered-noise tamper class must be understood as the case where refinement costs recall.

**Diagnostic worth its four lines:** if `raw_mask.mean() > 0.9`, set `info["suspect_parameters"]` with the message *"≥90% of blocks failed — far more likely a wrong key / ID / block size / variant than a 90% tamper."* This will save hours during the ablation sweep and in the demo, where a mismatched `variant` between embed and detect produces exactly this signature.

**Honest consequence of the channel-OR mask:** a tamper touching only the R channel flags the block, and recovery replaces all three channels with descriptor approximations, degrading untouched G and B. Confined to single-channel tampers, which our tamper classes do not produce. `per_channel` is returned raw if the ablation wants it.

**Effort: 0.5 day.**

### 4.5 `recover.py`

```python
class RecoverResult(NamedTuple):
    image, unrecoverable_mask, recovered_mask, rho, counts

def recover_image(received, det, block=8, variant="A", mark_unrecoverable=True, mark_value=0)
def recoverability_rate(block_mask, m) -> tuple[float, dict]   # image-free
```

`recoverability_rate` is separate and image-free on purpose: the harness can compute the theoretical ρ-vs-α curve from ground-truth masks with no embedding run — roughly 40× faster for that sweep.

**Three structural properties, each closing a named bug:**

1. **Descriptors are read from `det.desc_by_owner`, a snapshot taken before any pixel was written.** `recover_image` never reads an image LSB. So it is *impossible* for recovery of block `i` to read a descriptor out of a block recovery already overwrote. Had recovery read LSBs live, recovering a block first (zeroing its LSBs) then reading a descriptor from it would return all zeros and **silently fabricate flat grey content while reporting success.** Not "we are careful about ordering" — the data flow makes it unreachable.
2. **The mask is frozen.** `avail = d[m] == 0` is one vectorized expression evaluated before any write, so whether a partner is judged tampered cannot depend on when it is checked.
3. **Writes go into `out = img.copy()`**, never in-place on the array the masks came from.

**Consequence, asserted directly:** the output is invariant to iteration order. A test-only `_iter_order="reverse"` kwarg plus one `assert np.array_equal(fwd, rev)` closes the bug class. Ugly API, but the alternative is a second recovery implementation to test the first against.

**Unrecoverable marking:** `mark_value = 0` (flat black), default on. Explicit, visually unmistakable, never mistakable for content. **Never** inpaint, never copy neighbours, and never leave tampered pixels in place — leaving them would silently present attacker-supplied content as recovered output, the worst possible failure for this scheme.

The paper's optional harmonic-interpolation second stage is **out of scope for `recover.py`** — it belongs downstream, applied to the returned mask, reported in a separate table. It must never be merged into the primary recovery PSNR.

**Effort: 0.75 day.**

### 4.6 `test_e2e.py` — the keystone gate

**The keystone assertion:** embed, then immediately verify an untouched watermarked image → **zero blocks flagged**. Run across 5 images (natural-ish, flat black, flat white, 1-px checkerboard, full-entropy noise) × greyscale/colour × B∈{8,4} × variant∈{A,B} = 40 combinations.

**Must be asserted on `raw_mask` with `refine=False`.** On the refined mask, the 8-neighbour pass would silently clean up scattered false positives and a partially-broken MSB projection would still pass. Asserting pre-refinement is the whole point.

Any of these breaks it: hashing the raw block instead of `MSB(block)`; computing the descriptor before projection; embedding into 3 LSBs while projecting 2; computing the tag from the post-embedding block; a bit-order mismatch between embed and detect; a block-order mismatch between `to_blocks` and `from_blocks`.

**A second, independent assertion is mandatory — the `m`/`minv` canary.** Swapping `m` and `minv` between embed and detect still yields **zero flagged blocks**, because each block carries its own tag and tags are unaffected by which descriptor sits beside them. The keystone assertion cannot detect this. Without the canary, an `m`/`minv` swap ships silently and surfaces much later as inexplicably terrible recovered PSNR:

```python
own, _ = encode_descriptor(msb(to_blocks(plane, B)), variant, budget(B)[2])
assert np.array_equal(det.desc_by_owner[ch], own)
```

**Golden vectors:** fixed 16×16 image, fixed 32-byte key, checked-in expected map cycle, expected payload bytes for block 0 (both variants), expected `sha256` of the watermarked output, and a `sha256` of a K=4096 map. The payload bytes are pinned separately from the image hash so a bit-order change plus a compensating change elsewhere cannot pass — it localizes the failure to the packer.

Rule in the file header: *"These constants are a bit-exactness canary. If they fail, the default assumption is that a change broke the format — not that the constants are stale. Re-pinning requires a comment naming the deliberate change and confirming `test_keystone()` still passes."*

Because the keystream is HMAC-based, these vectors are stable across CPython versions, NumPy versions, OS, and CPU. With `random.Random` they would have been a version-bump tripwire; that risk was designed out.

**Effort: 0.5 day.**

---

## 5. Corpus

### 5.1 A problem with the plan in RESEARCH-FINDINGS.md

**USC-SIPI no longer distributes Lena or Tiffany.** The misc-volume page states it directly: *"we no longer distribute the following images that were previously available in our database: 4.2.04 (lena), 4.2.02 (tiffany)."* Since our 8-image set includes both, the official source cannot supply it.

**Primary source instead: `github.com/girfa/ColorImageDatasets`** (verified to exist) — maintained by the same group as the `AuSRResults` comparison data, containing exactly the corpora this literature uses: USC-SIPI 8 colour images at 512×512, Kodak-PCD0992 24 colour images at 512×768. Flat raw-fetchable URLs, no tarball extraction.

This is a *better* primary source than scraping USC-SIPI: it is exactly our 8-image list, and it is the same corpus AuSR1/2/3 report on, so our images are the same bytes their published tables are keyed to.

**Honest citation, following the convention `AuSRResults` itself uses:** *"the USC-SIPI and Kodak-PCD0992 sets as redistributed by the AuSR reference authors (github.com/girfa/ColorImageDatasets); original sources USC-SIPI (sipi.usc.edu) and Eastman Kodak (mirrored at r0k.us/graphics/kodak)."* USC's own removal already makes a byte-identical-to-today's-official-archive claim impossible, so this is field-standard, not an improvisation.

**Licensing:** USC-SIPI is research/education use with attribution; Kodak PCD0992 was released by Eastman Kodak for unrestricted use. Neither is redistributed commercially here. UCID (1,338 images) is available from the same mirror but **deliberately skipped** — not part of the 32-image grid, would 40× the runtime for zero required deliverable.

### 5.2 `samples/fetch_corpus.py`

Fallback chain, each tried only if the previous fails:
1. `raw.githubusercontent.com/girfa/ColorImageDatasets/main/...`
2. Per-file official mirrors — `sipi.usc.edu` for whichever USC images are still served (known incomplete: Lena and Tiffany are not), `r0k.us/graphics/kodak/` for Kodak (complete; unaffected by USC's removal)
3. If both fail: print the exact missing filenames and **exit non-zero — never silently proceed with a partial corpus.** A separate `--synthetic-fallback` generates labelled placeholder images so `tamper.py`/`metrics.py`/`run_experiments.py` can be developed offline. Rows with `dataset="synthetic"` are filtered out of every paper-facing table by a one-line guard, so a synthetic fallback can never leak into a submitted result.

**Verification model: trust-on-first-fetch, pin-and-verify after.** First run computes and records SHA-256 in `manifest.csv`, which is committed. Every later run re-hashes and compares — mismatch is a hard error, because a mirror silently changing bytes under a "reproducible" experiment is exactly what a manifest exists to catch.

Everything standardizes to PNG on ingest, so no module downstream sees anything else. Assert dtype stays `uint8` (cv2's TIFF reader can silently promote to 16-bit). Download to `.tmp` and rename only after a successful hash check, so a killed process cannot leave a file that exists-but-hashes-nothing and gets skipped.

**Effort: 0.5 day.**

---

## 6. Tamper simulation — `src/tamper.py`

**Seeding:** `derive_seed(base_seed, *parts)` = SHA-256 of the joined parts truncated to 63 bits, fed to `np.random.default_rng`. Never the legacy global `np.random.seed()` — it is process-global and unsafe once anything runs out of order.

**Region shapes:** rectangles for splice / crop-refill / noise, **deliberately not grid-aligned** (a block-aligned region would trivially make block precision 1.0 and hide the boundary-quantization effect the paper discusses). Irregular blob (union of 3–6 circles) for inpainting removal, since a real inpainting target is rarely an axis-aligned rectangle and `cv2.inpaint`'s behaviour genuinely differs on an organic hole.

**The four classes:**

| Class | Method | Expected behaviour |
|---|---|---|
| `splice` | paste a region from a *different* watermarked image (exercises the ID binding against collage attacks) | high recall |
| `inpaint_removal` | `cv2.inpaint` Telea/Navier-Stokes over a blob mask — **not** a constant fill, which is trivially detectable and unrealistic | **lowest recall, expected** — a smooth fill over flat content can numerically reproduce the original MSB planes near the hole boundary |
| `crop_refill` | synthetic filler (low-res noise, upsampled, blurred, tone-matched to the border ring) containing zero real captured content | high recall |
| `noise` | full destructive overwrite with uniform random bytes | ~100% recall, the sanity control |

**Ratios: 10%, 25%, 50%.** The 50% point is chosen deliberately to land on the theoretical collapse — where the `d_min = ¼·min(M,N)` separation guarantee stops covering the image and coincidence probability rises sharply.

### 6.1 Block-level ground truth — pinned rule

**A block is tampered iff the pixel-level intended region covers ANY pixel of it (OR-reduction), not a coverage-fraction threshold.**

Justification: the detector only ever outputs whole-block decisions — a flagged block's mask is the *entire* block, however small the damage inside it. Scoring ground truth at a different granularity than the detector's own quantization would bake in an asymmetry unrelated to the algorithm's real behaviour. "Any-pixel" is also the most conservative reasonable rule (largest possible GT region), so it cannot be accused of flattering our precision.

A `rule="majority"` variant is computed once per run as a free secondary column (pure numpy reduction on in-memory data) purely so a robustness footnote — *"results are qualitatively unchanged under a majority-pixel rule"* — can be produced if an examiner asks. This choice is exactly the kind that draws that question.

### 6.2 The coincidence trap — two distinct phenomena, never conflated

**Pixel-level coincidence:** a tamper can leave some pixels' exact values unchanged by chance (flat sky pasted on flat sky). **Rule: ground truth is the intended region geometry, decided before any pixel is written — never a post-hoc diff.** All four functions satisfy this by construction. `n_coincidental_unchanged_px` is computed and logged as a diagnostic, warned on above 0.5% of the region, never silently dropped.

**MSB-plane-preserving edits:** an edit can change raw pixel values while leaving a block's 6 MSB planes bit-identical (smooth inpainting over flat content). This causes an *expected* recall miss with a completely different cause. `metrics.py` tags these via `msb_preserved_miss_blocks()` so they are never miscounted as unexplained bugs — separating an expected miss from a real detector bug is exactly what an examiner probes.

**Structural guarantee, asserted with `==` not a tolerance:** outside the ground-truth mask, pixels are bit-identical to the input in every tamper function.

**Effort: 1 day.**

---

## 7. Metrics — `src/metrics.py`

**Imperceptibility, parameters pinned explicitly:**
```python
psnr = peak_signal_noise_ratio(original, watermarked, data_range=255)
ssim = structural_similarity(original, watermarked, data_range=255,
                             channel_axis=-1 if colour else None)
```
State in the paper: colour SSIM is the **mean of per-channel SSIM** (skimage's `channel_axis` behaviour), not SSIM of a luma conversion; `win_size` is the library default 7 with a uniform window, **not** Wang et al.'s 11×11 Gaussian. Pinned so a reader reproduces our numbers with that exact call. `psnr(a,a) == inf` stays `inf` in the CSV — clamping it would be a silent lie about a perfect match.

**Degenerate-case convention** (equivalent to sklearn's `zero_division=1` — a real citable convention, not invented): precision/recall/IoU default to 1.0 when their denominator is zero; F1 defaults to 0.0. Worked check that this hides nothing: total miss (`tp=0, fp=0, fn=100`) gives precision 1.0 (correctly — no false alarms raised) but recall, IoU, F1 all 0.0. Precision never masks a miss because it is never reported alone.

**Recovery metrics — in-region only.** Whole-image recovery PSNR is misleadingly high, and several published papers report exactly that.

The SSIM wrinkle: SSIM is windowed (7×7), so it cannot be validly masked-then-averaged like PSNR. Use `full=True` to get the per-pixel SSIM map, then index `S[mask]`. This is more correct than the common shortcut of cropping to the region's bounding box, which leaks non-tampered border pixels into a region-only number.

Masked PSNR is the one deliberate three-line reimplementation — skimage has no mask parameter, and bounding-box cropping has the same leakage problem.

**Reporting discipline enforced in code, not convention:**
```python
def format_recovery_row(row):
    assert "recoverability_rate" in row and "psnr_in_region" in row, \
        "recovery PSNR must never be formatted without recoverability_rate alongside it"
```
A future refactor that drops ρ raises here immediately instead of quietly emitting an inflated PSNR-only number into a table. Both an optimistic (`recoverable` mask) and pessimistic (`full GT` mask) PSNR are recorded.

### 7.1 TCBR / TCBD — verified as far as possible, not guessed

Confirmed from the publisher record: TCBR (Tamper Coincidence Block Ratio) and TCBD (Tamper Coincidence Block Density) measure exactly the phenomenon ρ measures, and are reported as negatively correlated with recovered PSNR/SSIM. **The exact formulas are not visible in any open-access abstract or preview — the article is paywalled.**

**Decision: implement only ρ. State the relationship qualitatively in the paper:** *"TCBR/TCBD (Aminuddin et al., 2024) are published metrics for the same tamper-coincidence phenomenon ρ measures here; their exact formulas were not accessible from open sources at time of writing, so we report ρ as our own precisely-defined quantity rather than assert numeric equivalence to an unverified formula."*

No formula is guessed. If institutional access appears later, a 10–30 minute follow-up either implements them exactly or confirms they are a monotonic transform of the same count. Optional enrichment, not a deliverable.

**Effort: 1–1.5 days.**

---

## 8. Experiment runner — `src/run_experiments.py`

**The grid: 1,184 rows.**

| Block | Composition | Rows |
|---|---|---|
| Main | 32 images × 4 tamper classes × 3 ratios × 2 variants | 768 |
| Null condition | 32 images × 2 variants × 5 keys, no tamper | 320 |
| Block-size ablation | 8 USC-SIPI × 4 classes × 3 ratios × Variant A × B=4 | 96 |

**Why 5 keys for the null condition, framed honestly.** The per-block false-accept probability is 2⁻³². No feasible number of trials could observe such an event by chance, and claiming otherwise would be dishonest. Repeating across keys is an **implementation-robustness check**: a content-dependent-but-key-independent bug (payload-layout off-by-one, serialization edge case triggered by one image's statistics) reproduces across keys; genuine cryptographic false accepts would not.

5 keys × 32 images × 2 variants × ~4,096 blocks ≈ **1.3M independent block verifications**. Report the honest statistic: a zero-events 95% "rule of three" upper bound is `3/1.3M ≈ 2.3×10⁻⁶` per block — real, computable, citable, meaningfully tighter than "trust the maths" without overclaiming what small-N shows about a 2⁻³² event.

**Ablation scope is restricted deliberately.** The question is "does the resolution/payload trade-off exist" — answerable from a fixed single-variant subset. Running the full 768-grid twice to answer a yes/no is waste, not thoroughness.

**The one real efficiency decision: cache the embed step.** `embed()` depends only on `(image, key, variant)` — not tamper class or ratio. Twelve grid cells share one embed call. Caching gives **64 embeds instead of 768.** Biggest wall-clock lever available, costs a lazily-populated dict.

**Critical correctness constraint, stated in the runner and repeated here:** `recover()` must be called with the **predicted** mask from `detect()`, **never** with `tamper.py`'s ground-truth mask. Ground truth is used only inside `metrics.py` for scoring. Feeding ground truth into `recover()` would silently convert the experiment into an oracle-localization measurement and invalidate every recovery number in the paper.

**CSV schema** — one row per run, ~38 columns, `run_id` a deterministic hash of the configuration (which doubles as the resumability key). Append mode, flush after every row, so a crash loses at most the in-flight row. `--restart` clears; default resumes.

**`--quick` mode:** 2 images, 1 ratio, 1 variant, 1 key → 10 runs, seconds. So the full grid is not run on every code change.

**Artifact retention: don't store what's regenerable.** Persisting images for all 1,184 runs is several GB for no benefit, since every run is bit-reproducible from its configuration. Only the qualitative figure set is kept (1 image × 4 classes × 1 ratio × 5 stages).

**Timing estimate:** ~0.3–0.8s per run before caching; full grid **under ~20 minutes** on a laptop CPU. To confirm once the core exists, not a promise.

**Effort: 1 day.**

---

## 9. Sanity gate — `src/sanity_gate.py`

The single highest-value piece of this plan. Reads `runs.csv`, checks aggregates against literature-derived bands, writes a report, **exits non-zero on any hard failure.** `make_tables.py` calls it first and refuses to write tables if it fails — so "generate tables from numbers nobody sanity-checked" is structurally impossible via the intended entry point.

**Hard checks:**

| Check | Band |
|---|---|
| watermarked PSNR mean | 43.5 – 44.2 dB |
| watermarked PSNR max | ≤ 44.20 (never exceeds the analytical bound) |
| watermarked SSIM mean | > 0.99 |
| **null-condition block FPR** | **exactly 0.0** |
| **whole-image** recovery PSNR mean @10% | 38 – 43 dB |
| **whole-image** recovery PSNR mean @25% | 33 – 38 dB |
| **whole-image** recovery PSNR mean @50% | 30 – 35 dB |
| **in-region** recovery PSNR mean (all ratios) | 28 – 36 dB |
| ρ monotonicity | ρ(10%) ≥ ρ(25%) ≥ ρ(50%) |
| no NaN/inf in ρ | — |

### 9.1 Correction: which PSNR the literature bands apply to

**Measured during implementation, before the runner was written.** Descriptor-only reconstruction PSNR — the hard ceiling on in-region recovery, since recovery cannot beat the descriptor it reconstructs from — is:

| variant | B=8 | B=4 |
|---|---|---|
| A (DCT) | 32.50 dB | 32.26 dB |
| B (mean-pool) | 33.05 dB | 31.13 dB |

So **in-region recovery PSNR is structurally capped near 32–33 dB** and can never reach the 38–43 dB band this plan originally demanded of it.

Resolving the discrepancy: modelling whole-image PSNR as a tampered fraction at 32.5 dB mixed with an untampered remainder at the 44.15 dB embedding floor reproduces the published bands almost exactly —

| tamper ratio | predicted whole-image | published band |
|---|---|---|
| 10% | 40.4 dB | 38 – 43 |
| 25% | 37.7 dB | 33 – 38 |
| 50% | 35.2 dB | 30 – 35 |

**Conclusion: the published recovery numbers (AuSR1, AuSR3, Wu 2025) are whole-image, not in-region.** They compare the recovered frame against the watermarked frame over the entire image, where the untampered majority sits at the embedding floor and dominates the MSE.

Consequences, all now implemented:
- `recovery_metrics` records **`psnr_whole` / `ssim_whole`** alongside the in-region and pessimistic figures.
- The **baseline comparison table must use the whole-image figure** — that is the only quantity comparable to the cited papers.
- The **in-region figure is the honest, stricter measure** and should be reported as our primary recovery metric, with the paper stating plainly that it is not the quantity prior work reports and why it is lower.
- Reporting only whole-image would flatter us. Reporting only in-region would look inexplicably poor next to the literature. Both go in, clearly labelled.

Had this not been caught, the sanity gate would have hard-failed on correct code at stage 13 and sent us hunting a bug that did not exist.

**Soft warning:** any single run with in-region PSNR < 20 dB.

**Why the ≥27 dB "bug floor" gates the per-ratio aggregate mean, not every row.** A genuinely fine method can have one high-texture image dip below 27 dB at 50% tamper from natural variance — that is not a bug, and gating all 1,184 rows against a hard floor would make the gate too brittle to trust. Hard-fail on aggregates (which sit above 27 dB with margin) catches a systemic bug; a looser 20 dB per-row soft warning catches true crashes (NaN, negative PSNR, all-black recovery) without false-alarming on normal spread.

**Why null FPR gets zero tolerance while everything else gets a band.** The deterministic-HMAC argument asserts it must be *identically* zero. Any nonzero value is definitionally an implementation defect — payload-layout bug, non-deterministic serialization, lossy I/O sneaking in — not natural variance. There is no legitimate reason for this number to be anything but 0.0.

**Effort: 0.5 day.**

---

## 9.2 Measured during implementation — a free ablation for the paper

Recoverability rate ρ on 512×512, B=8, real `tamper.py` regions, comparing our key-seeded constrained mapping against an unconstrained random permutation:

| tamper ratio | constrained map ρ | unconstrained shuffle ρ | unrecoverable blocks (ours vs naive) |
|---|---|---|---|
| 10% | **0.998 – 1.000** | 0.897 | 0–1 vs 45 (of ~440) |
| 25% | 0.77 – 0.84 | 0.730 | ~180–254 vs 302 |
| 50% | 0.49 – 0.69 | 0.485 | ~1050 vs 1088 |

Reading, and it should go in the paper as written:
- The minimum-separation constraint gives its **largest benefit at low tamper ratios** — which is the operationally common case — cutting unrecoverable blocks from 45 to ~0 at 10%.
- The benefit **shrinks as tamper area grows** and is **negligible at 50%**, because once half the image is destroyed no partner assignment can be far enough away. This is the theoretically expected collapse, not a defect.
- `inpaint_removal` behaves differently from the rectangular classes (ρ = 0.69 at 50% vs ~0.50) because its blob region is shaped differently — worth one sentence rather than being averaged away.

This is a genuine ablation obtained for free, and it is the honest way to present a design element that AuSR3 published first: we are not claiming the idea, we are quantifying when it helps and when it does not.

## 9.3 Correction: 44.15 dB is not an upper bound, and the paper must stop calling it one

**Measured, with the mechanism confirmed analytically.** The 44.15 dB figure is the expected PSNR for a **uniform** 2-LSB payload, derived from `E[(a−b)²] = 2·Var(uniform{0..3}) = 2.5`. It is a *value at a specific payload distribution*, not a ceiling — and neither of our variants has a uniform payload.

With original LSBs uniform, `E[e²] = E[a²] − 3·E[a] + 3.5` where `a` is the payload pair value. Measured payload pair distributions on full-entropy content:

| variant | pair distribution (0,1,2,3) | predicted | measured |
|---|---|---|---|
| A (DCT) | 0.361, 0.152, 0.150, 0.337 — **bimodal** | 43.51 dB | 43.21 dB |
| B (mean-pool) | 0.199, 0.305, 0.300, 0.196 — **centre-heavy** | 44.53 dB | 44.50 dB |

Both deviate, in opposite directions, for an understandable reason:

- **Variant A sits *below* 44.15.** Its quantized DCT coefficients are mostly near zero, so descriptor bytes are dominated by `0x00` (small positive) and `0xFF` (small negative in two's complement). Those pack into pair values 0 and 3 — the extremes — which are *farther* on average from a uniform original LSB than a uniform payload would be.
- **Variant B sits *above* 44.15.** A mean of already-quantized values concentrates toward the centre of its range, so pair values cluster at 1 and 2 — *closer* on average to a uniform original.

Consequences:

1. **Paper edit.** The claim "analytically bounded at ≈44.15 dB" is wrong as stated. Correct it to: 44.15 dB is the expected PSNR for a full-entropy payload; the realized value depends on the payload's value distribution, and is 43.2 dB for Variant A and 44.5 dB for Variant B for the reasons above. This is a *stronger* result than the original claim, because it is derived, predicted, and then confirmed to within 0.3 dB.
2. **The gate's `wm_psnr_max ≤ 44.20` hard check is wrong** and must be per-variant: ≤ 44.20 for A, ≤ 44.60 for B.
3. **An available free improvement, not yet taken.** XOR-ing the descriptor bits with an HMAC keystream before packing would whiten Variant A's payload to uniform, recovering ≈0.9 dB of imperceptibility for about three lines. It also closes a real weakness: as built, Variant A's LSB plane has a *visibly bimodal histogram*, so an attacker can distinguish watermarked from non-watermarked blocks by LSB statistics alone without the key. An examiner may well ask exactly that. Cost of doing it: the golden vectors must be regenerated. **Decision pending — not applied unilaterally, since it changes a verified module and a paper claim.**

## 9.4 Correction: the SSIM gate cannot be 0.99 unconditionally

**Measured on synthetic content of varying smoothness, B=8:**

| content noise σ | PSNR (A) | SSIM (A) | SSIM (B) |
|---|---|---|---|
| 2 | 43.08 | **0.9675** | 0.9690 |
| 5 | 43.12 | **0.9772** | 0.9802 |
| 8 | 43.18 | **0.9852** | 0.9881 |
| 15 | 43.27 | 0.9941 | 0.9955 |
| 30 | 43.34 | 0.9983 | 0.9987 |

PSNR is essentially flat at ~43.1–43.3 dB while SSIM ranges from 0.967 to 0.998. This is genuine SSIM behaviour, not a defect: SSIM's structure/contrast terms are normalized by local variance, so a fixed-variance embedding perturbation dominates on smooth content and is negligible on textured content.

**Process note worth recording.** The agent building `embed.py` hit this as a failing `SSIM > 0.99` assert and resolved it by raising its synthetic test image's noise from σ=8 to σ=15 — tuning the test until the gate passed, rather than asking whether the gate was right. The gate was the wrong part. Thresholds must be calibrated against the real corpus, never against a synthetic fixture that can be adjusted until it agrees.

**Action: the SSIM threshold is deferred until measured across all 32 real corpus images**, per variant, recording the minimum and which image produced it. Real photographs carry far more texture than a smooth synthetic gradient, so the real minimum should be much higher — but it will be measured, not assumed.

## 9.5 First end-to-end measurements, and what they mean for the paper's claims

Full pipeline (embed → tamper → detect → recover) on 512×512 synthetic content, Variant A, B=8. **Detection was perfect in every condition: precision 1.000, recall ≥ 0.998 across all four tamper classes at all three ratios.** Recovery is where the substance is.

### Whole-image recovered PSNR, and the marking penalty

| ratio | ρ | marking unrecoverable black | leaving unrecoverable as received | published band |
|---|---|---|---|---|
| 10% | 0.992 | ~17–25 dB | **35.0 dB** | 38–43 |
| 25% | 0.834 | ~17–25 dB | **29.3 dB** | 33–38 |
| 50% | 0.581 | — | **23.1 dB** | 30–35 |

Two separate effects, both now isolated:

**(a) Black marking costs 10–15 dB of whole-image PSNR.** Our default output marks unrecoverable blocks flat black rather than fabricating content — deliberately. But that makes our whole-image figure incomparable to papers that leave or interpolate such regions. **Action: the runner must record both a marked and an unmarked whole-image PSNR.** The marked figure describes our actual output; the unmarked figure is the only one comparable to the cited literature. State both, labelled.

**(b) We remain 3–8 dB below the published band even unmarked, and the reason is structural.** MSE decomposition of a 10% splice (ρ = 0.969):

| region | share of flagged area | MSE | PSNR |
|---|---|---|---|
| recovered blocks | 96.9% | 241.8 | 24.3 dB |
| unrecoverable blocks | **3.1%** | 17951 | **5.59 dB** |
| (of which: clean pixels inside flagged blocks) | 3.5% | 1435.8 | 16.6 dB |

**Whole-image recovered PSNR is dominated by the unrecoverable fraction, not by descriptor fidelity.** 3.1% of the region contributes more squared error than the other 96.9% combined. So ρ is the lever that matters, and a 1-to-1 partner mapping has a structural ρ ceiling that reference-sharing schemes (Zhang 2011, Korus & Dziech 2013) do not — which is precisely why Korus reports 37 dB at 50% damage using fountain codes for graceful degradation, while our discrete partner failures are all-or-nothing.

This is an honest, explained limitation, and Future Scope item 1 (reference-sharing / erasure-coded redundancy) is exactly its fix. The paper must say this plainly rather than implying parity.

### Descriptor fidelity is content-dependent — and the earlier 32.5 dB figure was optimistic

Recovered-block PSNR tracks the image's high-frequency content almost exactly, because 12 low-frequency DCT coefficients cannot represent fine detail:

| test content | noise σ | measured MSE | ≈ σ² | PSNR |
|---|---|---|---|---|
| §9.1 descriptor test | 6 | 36.6 | 36 | 32.5 dB |
| §9.5 pipeline test | 14 | 241.8 | 196 | 24.3 dB |

**Descriptor reconstruction error ≈ the magnitude of the detail the descriptor discards.** Every recovery number in this section is therefore *pessimistic* — the synthetic fixtures are noisier than real photographs. The corpus measurement supersedes them, and no recovery figure should be quoted in the paper until it is measured on the real corpus.

### Block over-coverage: a limitation to state, not a bug to fix

Detection is block-granular, so a block with one tampered pixel is flagged whole, and recovery then overwrites its clean pixels with a lossy descriptor — scoring 16.6 dB where leaving them untouched would score ~44. Worth about 1 dB overall (21% of region MSE). Inherent to the design, cheap to state, not worth a special case. The paper's existing block-quantization discussion is the right place for it.

## 9.6 Real-corpus measurements — imperceptibility is now settled

32 real images fetched, standardized to PNG, SHA-256 pinned in `samples/manifest.csv`. All gates below are validated against **all 32 images × both variants**, not against synthetic fixtures.

### Measured imperceptibility, USC-SIPI (block=8)

| image | PSNR-A | SSIM-A | PSNR-B | SSIM-B |
|---|---|---|---|---|
| airplane | 43.25 | 0.9773 | 43.95 | 0.9781 |
| baboon | 43.38 | 0.9938 | 44.37 | 0.9950 |
| house | 43.29 | 0.9840 | 44.21 | 0.9859 |
| lena | 43.23 | 0.9815 | 44.30 | 0.9839 |
| pepper | 43.27 | 0.9810 | 44.08 | 0.9816 |
| sailboat | 43.31 | 0.9860 | 44.17 | 0.9877 |
| splash | 43.23 | 0.9719 | 43.92 | **0.9707** |
| tiffany | 42.53 | 0.9805 | 44.33 | 0.9832 |

Aggregates over all 32: Variant A PSNR 42.21 / 43.18 / 43.38 (min/mean/max), SSIM 0.9719 / 0.9824 / 0.9942. Variant B PSNR 43.19 / 44.21 / 44.52, SSIM 0.9707 / 0.9844 / 0.9953.

### The SSIM gate was broken against real content, and is now fixed

`SSIM > 0.99` **fails 7 of the 8 USC-SIPI images on correct code**, and both variants' corpus means (0.982 / 0.984) sit below it. Ruled out a measurement artifact by testing three conventions — skimage's default 7×7 uniform, the Wang et al. 11×11 Gaussian that most watermarking papers use, and Gaussian-on-luma. **All three agree to within ~0.001**, so the window choice is not the explanation and our measurement stands.

Gate corrected to **`SSIM > 0.96`** — ~0.011 margin below the real minimum (0.97097, `splash`, Variant B, at a perfectly healthy 43.92 dB). A genuine regression lands far below 0.96 rather than just under it. Variant PSNR ceilings also raised to 44.30 (A) / 44.70 (B), since Variant B's real-corpus max is 44.52 dB — photographic content is not IID, so the noise-derived ceiling was too tight.

### Why our PSNR is ~2 dB below AuSR1, and why that is the right trade

AuSR1 reports 45.57 dB. The cause is **LSB shifting** — choosing the nearest pixel value whose LSBs match the payload, rather than replacing the LSBs outright:

| method | E[e²] | PSNR |
|---|---|---|
| LSB replacement (ours) | 2.50 | 44.15 dB |
| LSB shifting (AuSR1) | 1.50 | 46.37 dB |

**We cannot adopt it.** Shifting moves a pixel by ±4, which changes bit 2 — i.e. the MSB plane itself. The tag was computed over MSB(x); the verifier would hash a different value and every block would fail. Worked example: x=200, MSB=200, shift to 207 gives MSB=204 ≠ 200.

So there is a structural trade-off: **a scheme that authenticates the MSB plane is forced into LSB replacement and forfeits ~2.2 dB.** Schemes reporting higher PSNR via shifting either do not authenticate the shifted plane or require iteration to converge. This belongs in the paper as a stated design trade-off — it explains our number against the literature instead of leaving it looking like underperformance.

### Corpus facts worth knowing

- **6 of 24 Kodak images are portrait (512×768), not landscape (768×512)**: kodim04, 09, 10, 17, 18, 19. The blanket "512×768" in my plan was wrong. `blockmap.py` was already tested on non-square grids, so this is handled — but any hardcoded dimension assumption downstream would break.
- USC-SIPI's own `download.php` returns **HTTP 200 with an HTML notice page** for Lena and Tiffany, not an image. A status-code-only check would silently accept garbage; the fetcher only trusts a source after `cv2.imread` actually decodes it.
- The r0k.us Kodak path in my plan 404s — the real path has a doubled segment (`/kodak/kodak/`).
- Filenames confirmed via the GitHub Contents API rather than guessed: `airplane, baboon, house, lena, pepper, sailboat, splash, tiffany` (.tif), `kodim01..24` (.png).

## 9.7 A security defect found and fixed: the isolated-positive refinement rule

Surfaced while building the demo. A single transplanted block **correctly fails HMAC verification** (`raw_mask` = 1), and then `refine_mask`'s isolated-positive rule **erases it from the reported mask**. The production detection path was therefore missing single-block tampers entirely. At B=8 a single block is 64 pixels — ample to alter a digit on a financial instrument, a decimal point, or a small figure in a scanned document, which is precisely the high-value low-area edit the scheme exists to catch. The same rule also erased a correctly-detected block-transplant forgery.

Tested whether the rule earns its place, against grid data:

| evidence | result |
|---|---|
| false positives in `raw_mask`, all null rows | **exactly 0** — nothing for the rule to clean |
| raw vs refined precision / recall / F1 / IoU / FPR | **delta 0.00000** across 72 rows |
| rows where refinement raised F1 | **0** |
| single-block tamper detected, before fix | **no** |
| single-block tamper detected, after fix | **yes** |

All cost, no benefit. The rule's justification is suppressing bit-error false alarms, and for an exact keyed comparison that false-alarm rate is provably zero. It never fires usefully on the four attack classes either, since all produce contiguous regions where every flagged block has flagged neighbours.

**Fix:** `clear_isolated` now defaults to `False`. The isolated-*negative* fill is retained (it closes holes inside a tampered region at no comparable cost). The published behaviour remains available as a parameter so the paper reports both. Keystone gate still 40/40 after the change.

Generalizable point, now in the paper: **neighbourhood smoothing inherited from soft-decision detectors is not automatically appropriate to a hard-decision cryptographic one, where the false-alarm rate it exists to suppress is provably zero.**

## 9.8 Two of my own gate thresholds were wrong, and the gate caught them

**(a) "Marking can only hurt" is not a valid invariant.** I asserted `psnr_whole_marked <= psnr_whole_unmarked` as a hard check. Violated in 4.3% of rows. The arithmetic explains it: against uniform-random tampered bytes, `E[(mu-U)^2] = (mu-127.5)^2 + (255^2-1)/12`, versus `mu^2` for flat black — so black is farther from the truth for any true mean above ~90.

| true mean | MSE if marked black | MSE if left as random | marking better? |
|---|---|---|---|
| 30 | 900 | 14925 | yes |
| 128 | 16384 | 5419 | **no** |
| 200 | 40000 | 10675 | **no** |

Violations occur in `noise` and `crop_refill` — the two classes that write synthetic filler near the local mean, exactly where the arithmetic predicts black to lose. Demoted to a soft warning keyed on the *rate* rather than a class whitelist (the whitelist was too narrow and would need endless extension). Worth stating in the paper: flat black is chosen to be **visually unmistakable, not to minimise MSE** — a mid-grey marker would score better and read as content, defeating its purpose. The PSNR cost of honest marking is accepted deliberately.

**(b) The ratio-0.50 recovery band was extrapolated from synthetic fixtures.** I set an 18 dB floor from synthetic measurements of ~23 dB; the real corpus gives 17.79 dB. The code is not at fault — the value follows from measured ρ ≈ 0.55 at that ratio: about 45% of the tampered region stays unrecoverable, so ~22.5% of the frame still holds attacker content, predicting ~14.5 dB. **17.8 dB is better than the arithmetic predicts, not worse.** Independent evidence the pipeline is sound there: block precision 1.000, imperceptibility in band, ρ matching the theoretical collapse. Floor corrected to 13 dB from our own measurement — a mis-estimated band fixed, not a band widened to launder a bad run. Per-dataset: USC-SIPI 17.04 dB, Kodak 18.90 dB.

## 10. Tables and figures

`make_tables.py` generates **only the `tabular` body**, never the whole float — the paper's hand-written captions, labels, and positioning stay untouched, and a generated file can never clobber hand-tuned LaTeX.

Five tables:
1. `imperceptibility.tex` — per-image PSNR/SSIM for the 8 USC-SIPI images, both variants, plus a 32-image mean row
2. `localization_recovery.tex` — per tamper class, mean±std over 32 images, Variant A, with a footnote giving mean *achieved* ratio per nominal bucket so grouping-by-nominal is never mistaken for exact area matching
3. `null_condition.tex` — block and pixel FPR (must be exactly 0.0), the rule-of-three upper bound, and the n that produced it
4. `ablation_blocksize.tex` — 8×8 vs 4×4 with the payload-budget trade-off from §3.3 stated as the finding
5. `baseline_comparison.tex` — our measured numbers vs **cited published** AuSR1 / AuSR3 / Wu-2025 values, with an explicit footnote: *"values cited from their publications, not re-implementations."*

Per-image enrichment from `github.com/girfa/AuSRResults` is scoped as **optional** — using someone else's undocumented CSV schema is open-ended risk for marginal benefit over already-vetted summary numbers.

Figures (matplotlib, once installed): recovered-PSNR-vs-tamper-ratio curves with error bars, one line per tamper class, **distinct dash patterns not just colour** since IEEE papers get printed in B&W; plus a qualitative strip (original / watermarked / tampered / mask overlay / recovered).

**Effort: 1–1.5 days.**

---

## 11. Demo — `demo/app.py`

Built **last**, deliberately. A UI on untested logic hides bugs behind a nice screen and forces debugging through a web page instead of a terminal.

```
+----------------------+---------------------------------------------------------+
| SIDEBAR              | ROW 1  [Original] [Watermarked] [Tampered] [Recovered]  |
| load sample / upload |        captions: PSNR / SSIM vs original                 |
| secret key           | [ ] Amplify difference x50  -> reveals watermark pattern |
| image ID             +---------------------------------------------------------+
|                      | ROW 2  MASK REVEAL   (1) raw  (2) refined  (3) final     |
| tamper type (radio)  |        [ <- Back ]                    [ Next -> ]        |
| x0,y0,x1,y1 sliders  |        [ ] show partner-block links                      |
| [Apply Tamper]       +---------------------------------------------------------+
| presets:             | ROW 3  PSNR | SSIM | Prec | Recall | F1 | IoU | rho      |
|  [Corner] [Center]   +---------------------------------------------------------+
|  [Scatter 20%]       | ROW 4  [Run Tag-Transplant Attack]                      |
| [Detect] [Recover]   |        [Run Unrecoverable Demo]                         |
+----------------------+---------------------------------------------------------+
```

**Decisions:**

- **Presenter-advanced stage counter for the mask reveal, not a timed animation.** Streamlit reruns top-to-bottom on every interaction; a timed loop needs a blocking `sleep`+`rerun` that cannot pause cleanly for a judge's question. A stage counter is deterministic, replayable, and lets the presenter linger.
- **Rejected `streamlit-drawable-canvas`.** Four sliders plus three rehearsed presets. Zero new dependencies, and stage reliability on a laggy projector beats precise cursor control. Lead with presets; offer sliders as "and if I wanted exactly here…".
- **Cache on image *bytes*, not numpy arrays.** Hashing a few hundred KB is fast and stable; Streamlit's default numpy hashing has had version-dependent quirks.
- **The classic Streamlit bug this must not have:** a rerun silently regenerating the key and making everything look tampered. Fix: key and image ID set exactly once behind an `if "key" not in st.session_state` guard; embedding re-runs only when a content hash changes, never on an unrelated slider drag.

**A subtlety worth recording.** The staged reveal is supposed to show stray false positives getting cleaned up — but a *correct* HMAC produces **zero** false positives on a clean image, so there is nothing to clean. Fix: inject 2–3 synthetic bit-flips for that visualization only, labelled on screen as *"synthetic bit-errors injected for this demonstration only — not part of any measured result."* Honest teaching device; never touches the experiment path.

**The three set-pieces:**

**(a) Audience damages the image.** They pick the region; system localizes and repairs. The one place to walk the staged reveal slowly.

**(b) Tag-transplant attack — the credibility peak.** Copy a block carrying a *genuinely valid* HMAC tag from elsewhere in the same image into the tampered region, then detect. It still fires, because the tag binds `(ID, index, content)`. Needs no new interface — a pixel copy plus the existing `detect()` call. Full-width explanation panel, not a caption: *"Every byte in this region has a genuinely valid HMAC tag, cut from block #A of THIS image. Detection still fired at block #B because the tag is bound to (image ID, block index), not content alone. This is what defeats the Holliman–Memon (2000) block-collage counterfeiting attack."*

**(c) The honesty case — the closing beat.** Damage a block *and* its mapped partner. Output must be a visually unmistakable non-fabrication marker (solid magenta or hatched), never the tampered pixels left in place, which would read as "it did nothing" rather than "it told you the truth." Caption names the partner block index.

**Stage-safety guards:** upload restricted to PNG (JPEG rejected with *"PNG only — JPEG re-compression destroys the LSB payload by design; see Limitations"*, framed as the stated limitation rather than a bug); images >1024px resized; non-block-multiple dimensions cropped before any pipeline call; RGBA flattened; always boots from a bundled sample so there is no empty state.

**Headless smoke test:** all three set-pieces scripted through the same function calls the UI uses, run outside Streamlit, asserting mask non-empty after detect, recovered ≠ tampered in-region, detect still fires after transplant, unrecoverable mask non-empty after the coincidence case.

**Effort: 1–1.5 days.**

---

## 12. Build order

Non-negotiable, because each stage needs the *actual* output of the previous one to test against.

| # | Stage | Gate assertion before moving on | Effort |
|---|---|---|---|
| 0 | Scaffolding, pinned requirements, `pip install matplotlib` | imports succeed | 0.5 d |
| 1 | `payload.py` conventions + projection + blocking + tag | round-trips exact; tag changes on MSB change, unchanged on LSB-only change | 0.5 d |
| 2 | **`blockmap.py`** | R1 + R3 + inverse + R2 across all 5 corpus geometries; determinism; key sensitivity >99% | 1.0 d |
| 3 | `payload.py` descriptors | exact bit-width; `n_clipped == 0`; Variant B quantizer idempotent | 0.5 d |
| 4 | `embed.py` | `msb(wm) == msb(img)`; PSNR in **[42.0, 44.16]** | 0.5 d |
| 5 | `detect.py` | refinement rules on hand-built masks incl. corner fill; owner-reindex identity | 0.5 d |
| 6 | **KEYSTONE GATE** | 40/40 combinations flag zero blocks on `raw_mask` + the `m`/`minv` canary passes | — |
| 7 | `recover.py` | order-invariance; ρ consistency; region PSNR > 27 dB; unrecoverable marked not filled | 0.75 d |
| 8 | Golden vectors | `--regen`, paste, re-run green | 0.5 d |
| 9 | `tamper.py` | determinism; achieved ratio within tolerance; **outside-mask pixels bit-identical** | 1.0 d |
| 10 | `metrics.py` *(can start early, off critical path)* | identity checks; hand-computed 4×4 confusion grid; masked SSIM == library aggregate on a full mask | 1.0–1.5 d |
| 11 | `fetch_corpus.py` *(can start any time)* | 32 files, hashes pinned, idempotent, corruption detected | 0.5 d |
| 12 | `run_experiments.py` | `--quick` gives 10 rows; full grid gives 1,184 rows, zero NaN | 1.0 d |
| 13 | `sanity_gate.py` | every band checked; deliberately-corrupted input fails loudly | 0.5 d |
| 14 | `make_tables.py` + `plots.py` | every emitted number inside its literature band | 1.0–1.5 d |
| 15 | Paper + PPT corrections | §13 checklist; structural validation passes | 1.0 d |
| 16 | **`demo/app.py`** | headless smoke test of all 3 set-pieces | 1.0–1.5 d |
| 17 | Rehearsal + runbook | two full run-throughs on the real machine | 0.5 d |

**Critical path: ~11–13 days.** Stage 10 (metrics) and Stage 11 (corpus) are genuinely parallel — start them early against synthetic arrays. Paper corrections in Group A (§13) need no code and can run alongside anything.

**Stage 6 is a hard gate.** Every recovery number is meaningless until zero-false-positive verification holds. Debugging recovery on top of a broken projection wastes days.

**Highest overrun risks:**
1. **Stage 2 (`blockmap.py`)** — flagged by three reviewers. Mitigated by design: cycle notation makes R1 and R3 free, and testing happens on an abstract grid before any real pixel exists. *Fallback if still slipping after a day:* drop the separation-repair sophistication and use the simpler classical construction the paper already documents as a weaker alternative, purely to unblock stages 3–7, then circle back. No new prose needed — the trade-off is already written.
2. **Stages 5/7 integration** — first point real tampered images meet detect/recover, where descriptor bugs (zig-zag order, quantizer off-by-one) surface. Budget an extra 0.5 day not counted above.
3. **Stage 12 plumbing** — CSV schema drift, Windows paths, ratio-targeting off-by-one. Not compute time.

**Cut list, in order, if time runs short:**
1. **Variant B** — the paper already frames it as secondary ("low-complexity, microcontroller-class"). Report Variant A only; Variant B evaluation becomes future work.
2. **The 4×4 ablation** — RESEARCH-FINDINGS explicitly sanctions stating the trade-off in prose instead. The payload-capacity argument in §3.3 is already written.
3. **The transplant attack's manual source-block picker** (auto-pick stays).
4. **UCID corpus** — never in scope; listed so nobody scope-creeps it under pressure.

**Never cut:** the keystone gate, the `m`/`minv` canary, the blockmap assertions, the null-condition zero-FPR check, or any of the three demo set-pieces. Those are the entire credibility payload.

---

## 13. Paper and PPT corrections

### Group A — do now, no code needed

1. **Lin & Chang citation is a wrong-paper swap, not a date typo.** The `.tex` cites a real but *different* Lin & Chang paper (IEEE TCSVT vol. 11 no. 2 pp. 153–168, 2001) whose subject does not match what our own text describes it as doing. Replace with the verified entry: *C.-Y. Lin and S.-F. Chang, "Semi-fragile watermarking for authenticating JPEG visual content," Proc. SPIE 3971, pp. 140–151, 2000, DOI 10.1117/12.384968.* Rename the key and update all three `\cite` sites.
2. **The Zhang 2008 title is already correct** — RESEARCH-FINDINGS was wrong about this. The actual fix is to **add** the separate 2009 paper (Zhang, Wang & Feng, IWDW 2009, LNCS 5703) and cite both, so they are never conflated.
3. **Rename "partner-block collision" → "tamper coincidence problem"** everywhere (grep the whole repo, not just the `.tex` — also RESEARCH-FINDINGS.md, EXPLAIN-SIMPLE.txt, PPT_Content.txt), citing AuSR3 (2023) at first use.
4. **Demote the block mapping** from "our contribution" to "established approach, our implementation" — AuSR3 published the distant-mapping idea first. Reposition the contribution as the specific single-cycle-permutation construction plus the rest of the pipeline.
5. **Reconcile ρ against TCBR/TCBD** with the qualitative statement drafted in §7.1. Add the bibitem.
6. **Retire the "detection-only prior art" framing.** Mild in the `.tex`; sharp in the PPT — slide 2, slide 4, slide 14's comparison table (add a "learned proactive watermarking" column: Recovers=Yes, Explainable=No, Deterministic=No), slide 17. Add a Related Work paragraph citing EditGuard (CVPR 2024), DeepMark (2026), RecoverMark (2026), and rewrite the contribution claim to the repositioned version.
7. **Add citations:** the 2019 EURASIP survey as field overview with its transparency/detection/recovery framing; arXiv:1812.11735 at the Keyed Authentication Tag section as the *justification* for keyed HMAC rather than a bare assertion.
8. **Remove all 15 `[VERIFY CITATION DETAILS]` markers.** 13 resolve from RESEARCH-FINDINGS §1. **Two do not** — the markers flagging "Wu and Liu" and "He, Zhang et al." reference papers research never confirmed exist as described. **Delete those sentence fragments and their citations outright.** An absent claim is safer than an unverified one.
9. **Add the state-of-the-art comparison table** (structure and cited columns now; our column after Stage 14).
10. **Add the honest 8×8-vs-2×2 weakness paragraph**, reusing the payload-capacity trade-off already reasoned out in the draft.

### Group A2 — four corrections found during implementation planning

11. **§Recovery Descriptor Construction:** `L=10` → `L=12`; replace the decreasing-allocation sentence with uniform 8-bit fields and per-band step sizes. The current three claims are mutually inconsistent (§4.2).
12. **§Notation:** "symmetrically padded" → cropped to the largest block-aligned region, with the crop reported (§4.2).
13. **§Tamper Detection:** note that τ is applied as `⌈τ·|N(i)|/8⌉` at borders, or border blocks are silently exempt from the fill rule (§4.4).
14. **§Reproducibility:** state that block indices entering the HMAC are **0-based**; that colour uses one shared mapping with per-channel tags and a channel-OR mask; and add the two provable bounds (2-LSB embedding into an MSB-projected image cannot overflow; retained DCT coefficients cannot clip at 8 signed bits).

### Group B — needs real numbers (after Stage 14)

15. Replace Table I. **Catch:** the placeholder image names (Barbara, Goldhill, Cameraman) are **not in** the USC-SIPI 8-image set we selected — this is a re-selection, not a number fill.
16. Fix the "Mean (40 images)" label → **32 images** (8 USC-SIPI + 24 Kodak).
17. Replace Table II; replace "0 false-positive pixels over all 40 images" with the real count and a confirmed real zero.
18. Finalize the comparison table's "our" column.
19. **Regenerate `slides.pptx`.** `build_ppt.py` hardcodes content in Python literals; `PPT_Content.txt` is a hand-maintained mirror, **not** auto-synced. Both must be edited, then `python ppt/build_ppt.py`.

### Group C — validation without a LaTeX distribution

No LaTeX is installed locally. Structural checks via short scripts: label/ref cross-check; cite/bibitem cross-check (highest value right after the key renames in A1/A2/A8); environment and brace balance. Then **Overleaf** for an actual compile once A and B land — a final gate, not a substitute, since Overleaf reports the first error rather than whether every reference makes semantic sense.

---

## 14. Presentation-day runbook

**Pre-load:** environment verified that morning; Streamlit already running and warmed; app booted on a bundled sample, never an empty upload state; fixed key and image ID on a printed card; fallback assets staged in `output/` — a short screen recording of each set-piece succeeding, plus pre-computed result images and the tables as PDF.

**Rehearse twice on the actual machine and projector.** Verify mask overlay colours and metric text are legible at distance. Memorize talking points to each "Next stage" click. Rehearse recovering from an accidental upload so the guard messages don't throw you. Time-box to 4–6 minutes and know in advance what to skip.

**Order — weak to strong:**
1. Amplify-difference toggle (low risk, establishes invisibility, warms the room)
2. Set-piece (a), audience damages it — the one place to run the staged reveal slowly
3. Set-piece (b), tag-transplant attack — the credibility peak, placed second-to-last
4. Set-piece (c), the honesty case — closing beat: *"when it truly can't recover something, it says so instead of making something up."*

**If the demo misbehaves:** switch to the pre-recorded clip immediately, already open and paused at frame 0, with one spoken line. Never debug a traceback on screen. If Streamlit won't launch at all, fall back to pre-computed images and a walkthrough of the tables — the paper becomes the demo.

---

## 15. Effort summary

| Area | Effort |
|---|---|
| Core algorithms (payload, blockmap, embed, detect, recover, tests) | ~4.25 days |
| Corpus + tamper + metrics | ~2.5–3 days |
| Experiment runner + sanity gate + tables + figures | ~3–3.5 days |
| Demo UI | ~1–1.5 days |
| Paper + PPT corrections | ~1 day |
| Rehearsal | ~0.5 day |
| **Total, with the parallelism noted in §12** | **~11–13 days** |

---

## 16. Cross-module interface contracts

Recorded so the modules cannot drift apart:

- **One PSNR/SSIM implementation only** — `metrics.image_metrics`. `embed.py` imports it from there; nothing reimplements it. A second PSNR with a different `data_range` or SSIM `channel_axis` is how two parts of the same project end up disagreeing by 0.3 dB. *(Moved from `embed.py` to `metrics.py` at build time: the metrics module owning metrics is the cleaner dependency direction, and it lets `metrics.py` be written in parallel with the core.)*
- **`embed`/`detect`/`recover` all take `image_id` explicitly.** The HMAC binds it, so it cannot be implicit.
- **`block_size` and `variant` are parameters, never module-level constants** — otherwise the ablation and the two-variant grid need monkey-patching.
- **`DetectResult` carries both `raw_mask` and `block_mask`.** Report metrics for both; the isolated-positive rule costs recall on scattered tampers.
- **`RecoverResult.counts`** exposes raw |T|, |U|, K so TCBR/TCBD can be computed later without re-plumbing.
- **Detection over-covers unaligned tampers** by up to one block on each edge. The harness must define TPR/FPR against block-quantized ground truth, or report the quantization separately.
- **`recover()` receives the predicted mask, never ground truth.** Violating this silently turns the experiment into oracle-localization.
- **`info["suspect_parameters"]`** is set when ≥90% of blocks fail. The demo surfaces it as "wrong key or settings?" rather than displaying a 90%-tampered result.
- **No JPEG save path anywhere**, in any module or UI.
