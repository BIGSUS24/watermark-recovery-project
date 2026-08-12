"""Foundation module for the watermark-recovery project.

Keys, geometry, MSB projection, block authentication tags, DCT-based
recovery descriptors, and LSB bit/pixel plumbing. No internal dependencies
-- only numpy and stdlib (hmac, struct). Every other module in the project
imports this one.

Shared conventions (binding for every module in this project):
- Images: np.uint8, range 0..255. Greyscale (H, W); colour (H, W, 3) in RGB order.
- Block stacks: (K, B, B) uint8, raster block-row-major order.
- Bit arrays: np.uint8 holding only 0 or 1. NEVER bool -- mixing invites
  silent broadcasting bugs.
- Bit order: MSB-first / big-endian EVERYWHERE. np.unpackbits default,
  int.to_bytes(..., 'big'), struct '>' prefix. One rule, zero per-site
  decisions.
- Block indices: 0-based in code.
- DCT in float64. Any integer arithmetic that can exceed 255 casts to
  np.int16 FIRST -- NumPy 2 keeps uint8 * python_int as uint8 and wraps
  silently.
- Descriptor variant: the literal string "A" or "B".
"""

import hmac
import struct

import numpy as np

KEY_LABEL_TAG = b"wgtlr/v1/tag"
KEY_LABEL_MAP = b"wgtlr/v1/map"

# Format magic + variant codes for the tag message header (see block_tags).
VARIANT_CODE = {"A": 1, "B": 2, "C": 3}

# JPEG-50 luminance quantization table read in zig-zag order, DC entry replaced by 8.
DELTA_ZZ = np.array([8, 11, 12, 14, 12, 10, 16, 14, 13, 14, 18, 17, 16, 19, 24, 40],
                    dtype=np.float64)

# --------------------------------------------------------------------------
# Variant C tables -- rate-distortion-optimized descriptor (block=8 only)
# --------------------------------------------------------------------------
# WHY C EXISTS. Variant A spends its 96 descriptor bits as 12 zig-zag DCT
# coefficients at a FIXED 8 bits each. Measured on a scanned-document photo,
# reconstructing the whole image from intact descriptors with zero tampering
# tops out at 23.86 dB -- and real measured recovery of a pen-scribbled region
# came in at 23.0 dB, i.e. 96% of that ceiling. The tamper mapping was not the
# bottleneck; the descriptor was. Twelve of 64 coefficients is a severe
# low-pass filter, and text is broadband, so document content is the worst
# case for A by construction.
#
# A's own no-clipping proof is what exposes the waste: it shows every AC
# coefficient uses at most 1024/10 = 102.4 of int8's +-127 range. That slack is
# paid for in every block and never used. C reallocates it: coefficient COUNT,
# not coefficient PRECISION, is what document content is starved of.
#
# THE LAYOUT. 96 bits = 1 mode bit + 95 bits of coefficient fields.
#   bit 0        : which table this block used (0 = smooth, 1 = detailed)
#   bits 1..95   : signed two's-complement fields, MSB-first, in zig-zag
#                  order, of the per-position widths in C_BITS[mode].
# The encoder reconstructs the block BOTH ways and keeps whichever is actually
# closer in pixel space, so mode selection is exact rather than heuristic.
# One bit of side information buys about a dB of mean fidelity over a single
# table and -- the reason it ships -- turns a worst case into a guarantee. A
# single table regressed one smooth low-detail corpus image (tiffany) by 1.92 dB;
# the dual table regresses nothing. Measured on 13 held-out corpus images the fit
# never saw, plus the synthetic document: mean +3.19 dB over variant A, worst case
# +2.33 dB, i.e. EVERY image improves. That "never worse" property, not the mean,
# is what makes C safe to default to; src/fit_variant_c.py asserts it.
#
# The mode bit needs no extra protection: it lives in the descriptor field,
# and block_tags() already binds every carried descriptor bit into the HMAC.
#
# UNLIKE VARIANT A, SATURATION IS DELIBERATE HERE. A 2-bit AC field holds only
# -2..1, so real content clips -- and that is the optimum, not a defect: the
# step sizes below were chosen by measuring true squared error INCLUDING
# saturation and picking the minimum, so trading rare large-coefficient
# clipping for finer everyday resolution is a decision the numbers made. C
# therefore REPORTS its saturation count instead of asserting it is zero. Do
# not copy A's `assert n_clipped == 0` onto this variant.
#
# PROVENANCE / REPRODUCIBILITY: both tables are the output of
# `python src/fit_variant_c.py`, which re-derives them from the corpus and
# asserts they match these literals exactly. They are NOT hand-tuned, and they
# are NOT fitted per image -- one fixed table pair, baked into the format, the
# way JPEG bakes in its quantization tables. Training set: the 8x8 DCT
# statistics of one high-frequency near-greyscale document scan plus the first
# three corpus photographs. That mix is load-bearing. Fitting on the document
# alone starves chroma and cost a saturated-colour image 7.3 dB; fitting on
# photographs alone leaves document text blurred.
C_DESC_BITS = 96          # variant C is defined for block=8 / 96 descriptor bits only
C_MODE_BITS = 1

# Bits per zig-zag position. Each row sums to exactly 95.
C_BITS = (
    # mode 0 -- smooth blocks: 34 coefficients, fine DC (8 bits)
    (8, 4, 5, 4, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 3, 2, 2, 2,
     2, 2, 2, 2, 0, 0, 1, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
     0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    # mode 1 -- detailed blocks: 31 coefficients, coarser DC, much wider AC steps
    (7, 5, 5, 4, 4, 5, 5, 4, 3, 4, 3, 3, 3, 3, 4, 3, 2, 2, 2, 2, 3, 2, 2, 2,
     2, 2, 2, 2, 1, 0, 0, 0, 2, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
     0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
)

# Quantization step per zig-zag position, 0 where that position carries no bits.
# A width of 1 is legal and appears in both tables: a 1-bit signed field encodes
# {-1, 0}, which the allocator measured as worth more than nothing at a position
# where 2 bits would have to come out of somewhere better.
C_STEPS = (
    (7.6187, 9.9764, 6.39, 7.404, 6.8901, 7.6729, 9.6646, 8.7721, 8.6625,
     10.2742, 8.1416, 6.6205, 6.8937, 6.4824, 7.4243, 6.6982, 7.5421, 8.5813,
     8.2487, 8.7058, 7.4378, 7.7674, 7.4551, 6.7384, 6.8971, 6.6603, 6.1293,
     6.5289, 0.0, 0.0, 6.1632, 5.584, 5.6883, 5.6441, 6.4359, 5.7916, 0.0,
     0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
     0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    (12.7222, 35.0876, 33.5106, 35.8346, 28.7572, 29.0145, 22.6791, 22.7167,
     29.9529, 26.5759, 35.6076, 24.2035, 24.4592, 30.5164, 28.4422, 29.3887,
     35.5397, 29.8628, 30.1685, 36.7847, 27.8788, 28.8257, 26.8867, 26.9329,
     24.5621, 23.0053, 22.4481, 29.2487, 24.9814, 0.0, 0.0, 0.0, 22.9585, 0.0,
     0.0, 22.2559, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
     0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
     0.0, 0.0, 0.0),
)

assert len(C_BITS) == len(C_STEPS) == 2
for _m in (0, 1):
    assert len(C_BITS[_m]) == len(C_STEPS[_m]) == 64
    assert sum(C_BITS[_m]) + C_MODE_BITS == C_DESC_BITS, sum(C_BITS[_m])
    # A position with bits must have a step, and a position without bits must not.
    assert all((w > 0) == (s > 0) for w, s in zip(C_BITS[_m], C_STEPS[_m]))


# --------------------------------------------------------------------------
# Key derivation
# --------------------------------------------------------------------------

def coerce_key(key: bytes | str) -> bytes:
    """Accept a str passphrase (UTF-8) or raw bytes; return master key bytes."""
    return key.encode("utf-8") if isinstance(key, str) else key


def subkey(key: bytes | str, label: bytes) -> bytes:
    """Derive a 32-byte domain-separated subkey: HMAC-SHA256(key, label)."""
    # ponytail: HMAC-with-label as the KDF instead of HKDF -- two fixed,
    # independent labels (tag/map) need no extract-then-expand ceremony.
    # Upgrade to HKDF if the project ever grows past a handful of subkeys.
    return hmac.digest(coerce_key(key), label, "sha256")


# --------------------------------------------------------------------------
# Image identifier
# --------------------------------------------------------------------------

def default_image_id(stem: str, shape: tuple[int, ...], block: int) -> bytes:
    """Deterministic reproducible ID for research runs: b'stem|HxW|B'.

    This ID is caller-supplied side information -- it must NEVER be derived
    from pixel content. A content-derived ID is self-defeating: tampering
    changes content, so a content-derived ID would change right along with
    the tamper and every block would fail verification regardless of what
    actually changed, defeating the point of a keyed tag.

    Production use requires a fresh random >=128-bit nonce per image
    (secrets.token_bytes(16)), NOT this function: reusing an ID across
    images permits a cross-image block transplant at the same block index,
    since the tag would then depend only on (key, geometry, index, content).
    """
    h, w = shape[0], shape[1]
    return f"{stem}|{h}x{w}|{block}".encode("utf-8")


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------

def budget(block: int) -> tuple[int, int, int]:
    """(capacity_bits, tag_bits, desc_bits) for one block x block region at 2 LSBs/pixel."""
    cap = 2 * block * block
    tag = min(32, cap // 2)  # never spend more than half the block on the tag
    desc = cap - tag
    assert tag % 8 == 0 and desc % 8 == 0
    return cap, tag, desc


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def crop_to_blocks(img: np.ndarray, block: int) -> tuple[np.ndarray, tuple[int, int]]:
    """Crop bottom/right so H and W are multiples of block; return (cropped, (dh, dw))."""
    h, w = img.shape[0], img.shape[1]
    dh, dw = h % block, w % block
    cropped = img[: h - dh, : w - dw]
    return cropped, (dh, dw)
    # ponytail: crop, never pad. Padding would put real blocks' descriptors
    # into phantom blocks that get discarded on the way back out, making
    # those real blocks unrecoverable by construction -- a correctness hole,
    # not a shortcut. Every corpus image here (512x512, 512x768, 512x384) is
    # already a multiple of 8 and 4, so this branch never fires on results.


def to_blocks(plane: np.ndarray, block: int) -> np.ndarray:
    """(H, W) uint8 -> (K, block, block) uint8 in raster block order."""
    h, w = plane.shape
    bh, bw = h // block, w // block
    reshaped = plane.reshape(bh, block, bw, block)
    return reshaped.transpose(0, 2, 1, 3).reshape(bh * bw, block, block)


def from_blocks(blocks: np.ndarray, shape: tuple[int, int], block: int) -> np.ndarray:
    """Inverse of to_blocks."""
    h, w = shape
    bh, bw = h // block, w // block
    reshaped = blocks.reshape(bh, bw, block, block)
    return reshaped.transpose(0, 2, 1, 3).reshape(h, w)


# --------------------------------------------------------------------------
# MSB projection -- the keystone operator
# --------------------------------------------------------------------------

def msb(a: np.ndarray) -> np.ndarray:
    """MSB projection: zero the two LSBs of every pixel (a & 0xFC).

    This is the single most important function in the project. All hashed
    and compressed payload is computed on the projected image, so embedding
    never invalidates its own payload.
    """
    return a & np.uint8(0xFC)


# --------------------------------------------------------------------------
# Authentication tag
# --------------------------------------------------------------------------

def block_tags(blocks_msb: np.ndarray, key: bytes | str, image_id: bytes,
               shape: tuple[int, int], block: int, channel: int, variant: str,
               tag_bits: int, carried_desc: np.ndarray | None = None) -> np.ndarray:
    """(K, tag_bits) uint8 bit array: truncated HMAC-SHA256 tag per block, MSB-first.

    `carried_desc` is the (K, desc_bits) uint8 bit array of the recovery descriptor
    that each block PHYSICALLY CARRIES in its own LSBs -- i.e. `desc[minv]` at embed
    time, and the descriptor bits actually extracted from the received image at
    detect time. Binding it closes a vulnerability that the first version of this
    scheme had:

    The tag used to cover only `msb(b_i)`. But a block's 128 payload bits are a
    32-bit tag in pixels 0-15 plus a 96-bit descriptor in pixels 16-63 -- so 48 of
    64 pixels, three quarters of everything embedded, had NO integrity protection.
    An attacker needing no key could flip the 2 LSBs of pixels 16-63 in every block,
    destroying every recovery descriptor in the image at 40.29 dB PSNR and a maximum
    pixel delta of 3, and the detector would flag 0 of 4096 blocks -- certifying the
    gutted image as authentic. Then, combined with a visible edit, the scheme would
    report rho = 1.0000 and zero unrecoverable blocks while reconstructing every
    flagged block from attacker-chosen bits: exactly the "silently present
    attacker-supplied content as recovered" failure that recover.py is written to
    prevent. Verified by direct exploit before the fix.

    Binding costs ZERO extra payload bits. The embedder already has `desc[minv]`;
    the verifier already extracts the stored descriptor before comparing tags. The
    format magic is bumped to WGT2 so a watermark made by the old, vulnerable
    version fails loudly against this verifier instead of silently verifying.

    `carried_desc=None` reproduces the old unbound message and exists ONLY so the
    vulnerability can be demonstrated in the paper's security discussion. It must
    never be used to embed.
    """
    # Structurally prevents the single most damaging bug in the project:
    # hashing the raw block instead of the MSB-projected one. Kept in
    # production, not behind a debug flag.
    assert np.all(blocks_msb & 0x03 == 0)

    M, N = shape
    K = blocks_msb.shape[0]
    tag_bytes = tag_bits // 8
    sk = subkey(key, KEY_LABEL_TAG)  # derive once, not per block -- K is 4096-16384/channel
    id_prefix = len(image_id).to_bytes(2, "big") + image_id

    if carried_desc is not None:
        if carried_desc.shape[0] != K:
            raise ValueError(f"carried_desc has {carried_desc.shape[0]} rows, expected {K}")
        # Pack the descriptor bit array to bytes once, outside the loop. desc_bits is
        # a whole number of bytes for every supported block size (see budget()).
        desc_bytes = np.packbits(carried_desc.astype(np.uint8), axis=1)
        magic = b"WGT2"
    else:
        desc_bytes = None
        magic = b"WGT1"   # legacy, vulnerable -- demonstration only

    out = np.empty((K, tag_bits), dtype=np.uint8)
    for i in range(K):
        msg = (
            # magic: format version. WGT2 binds the carried descriptor; WGT1 did
            # not. Bumping it means an old watermark fails loudly against a new
            # verifier instead of silently verifying wrong.
            # M, N, block, channel, variant: geometry, block-size, cross-
            # channel and variant confusion are all made impossible.
            struct.pack(">4sHHHBBI", magic, M, N, block, channel, VARIANT_CODE[variant], i)
            # i (0-based): intra-image block transplant impossible
            # (Holliman-Memon 2000 collage attack).
            # image_id, LENGTH-PREFIXED: without the prefix, ID=b"AB", i=1
            # could collide with ID=b"A", i=... via plain concatenation --
            # a textbook mistake, the prefix is not optional.
            + id_prefix
            + blocks_msb[i].tobytes()
            # carried descriptor: closes the unauthenticated-payload hole above.
            + (desc_bytes[i].tobytes() if desc_bytes is not None else b"")
        )
        # hmac.digest (module-level one-shot), not hmac.new(...).digest():
        # ~3x faster in CPython for short messages, and this runs K times.
        digest = hmac.digest(sk, msg, "sha256")[:tag_bytes]
        out[i] = np.unpackbits(np.frombuffer(digest, dtype=np.uint8))
    return out
    # ponytail: this per-block Python loop is ~8ms per channel at K=4096.
    # Vectorizing SHA-256 itself is not possible in stdlib; if K ever reaches
    # millions, batch through a C extension (e.g. hashlib's OpenSSL backend
    # driven from Cython/numba) instead of rewriting this loop in pure numpy.


# --------------------------------------------------------------------------
# DCT helpers
# --------------------------------------------------------------------------

def dct_matrix(block: int) -> np.ndarray:
    """Orthonormal 1-D type-II DCT matrix D, so C = D @ X @ D.T for a 2-D block."""
    # ponytail: an explicit D @ X @ D.T instead of cv2.dct -- cv2.dct only
    # takes a single 2-D array, so blockwise use would mean K Python-level
    # calls, whereas this matmul broadcasts over the whole (K, B, B) stack
    # in one shot, is block-size generic (B=4 needed for the ablation), and
    # has an exact one-line inverse (D.T @ C @ D). Cost is ~2 MB of float64
    # at K=4096 -- irrelevant. Keeps OpenCV out of the numerics entirely.
    B = block
    n = np.arange(B)
    k = np.arange(B).reshape(B, 1)
    D = np.sqrt(2.0 / B) * np.cos(np.pi * (2 * n + 1) * k / (2 * B))
    D[0, :] = np.sqrt(1.0 / B)
    return D


def zigzag_indices(block: int) -> list[tuple[int, int]]:
    """JPEG zig-zag scan order for a block x block array."""
    B = block
    coords = [(i, j) for i in range(B) for j in range(B)]

    def key(ij: tuple[int, int]) -> tuple[int, int]:
        i, j = ij
        s = i + j
        return (s, j if s % 2 == 0 else i)

    return sorted(coords, key=key)


# --------------------------------------------------------------------------
# Recovery descriptors
# --------------------------------------------------------------------------

def _c_check(block: int, desc_bits: int) -> None:
    """Variant C is a block=8 format. Fail loudly rather than mis-pack."""
    if block != 8 or desc_bits != C_DESC_BITS:
        raise ValueError(
            f"variant C is defined for block=8 / {C_DESC_BITS} descriptor bits only, "
            f"got block={block} / desc_bits={desc_bits}. Use variant A or B for other "
            f"block sizes (the block=4 ablation runs on A), or regenerate a table pair "
            f"for that width with src/fit_variant_c.py.")


def _c_quantize(coef: np.ndarray, mode: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(K,64) coefficients -> (codes, dequantized, per-block saturation count) for one mode."""
    bits, steps = C_BITS[mode], C_STEPS[mode]
    q = np.zeros(coef.shape, dtype=np.int64)
    deq = np.zeros(coef.shape, dtype=np.float64)
    nsat = np.zeros(coef.shape[0], dtype=np.int32)
    for i, w in enumerate(bits):
        if not w:
            continue
        lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
        # np.rint (round-half-to-even) for the same reason variant A uses it:
        # int() truncation biases every coefficient toward zero.
        raw = np.rint(coef[:, i] / steps[i])
        nsat += ((raw < lo) | (raw > hi)).astype(np.int32)
        q[:, i] = np.clip(raw, lo, hi)
        deq[:, i] = q[:, i] * steps[i]
    return q, deq, nsat


def _c_idct(deq: np.ndarray, block: int) -> np.ndarray:
    """(K,64) zig-zag dequantized coefficients -> (K,B,B) uint8 reconstruction, LSBs zeroed."""
    zz = zigzag_indices(block)
    Cz = np.zeros((deq.shape[0], block, block), dtype=np.float64)
    Cz[:, [r for r, _ in zz], [c for _, c in zz]] = deq
    D = dct_matrix(block)
    return np.clip(np.rint(D.T @ Cz @ D + 128.0), 0, 255).astype(np.uint8) & np.uint8(0xFC)


def _c_pack(q: np.ndarray, mode: int) -> np.ndarray:
    """(K,64) codes -> (K,96) bit array: mode bit, then MSB-first two's-complement fields."""
    out = np.zeros((q.shape[0], C_DESC_BITS), dtype=np.uint8)
    out[:, 0] = mode
    off = C_MODE_BITS
    for i, w in enumerate(C_BITS[mode]):
        if not w:
            continue
        # & mask turns the signed code into its w-bit two's-complement pattern; the
        # decoder's sign-extension below is the exact inverse. Same free round-trip
        # variant A gets from int8's byte view, just at an arbitrary width.
        u = q[:, i] & ((1 << w) - 1)
        out[:, off:off + w] = (u[:, None] >> np.arange(w - 1, -1, -1)[None, :]) & 1
        off += w
    assert off == C_DESC_BITS, off
    return out


def _c_unpack(desc: np.ndarray, mode: int) -> np.ndarray:
    """(K,96) bits -> (K,64) dequantized coefficients, decoding with one mode's table."""
    deq = np.zeros((desc.shape[0], 64), dtype=np.float64)
    off = C_MODE_BITS
    for i, w in enumerate(C_BITS[mode]):
        if not w:
            continue
        u = desc[:, off:off + w].astype(np.int64) @ (1 << np.arange(w - 1, -1, -1))
        # Sign-extend: anything at or above half the range is negative.
        q = u - ((u >= (1 << (w - 1))) << w)
        deq[:, i] = q * C_STEPS[mode][i]
        off += w
    assert off == C_DESC_BITS, off
    return deq


def encode_descriptor(blocks_msb: np.ndarray, variant: str, desc_bits: int
                      ) -> tuple[np.ndarray, int]:
    """(K, desc_bits) uint8 bit array compressing each MSB-projected block; also n_clipped.

    Variant A keeps the first n_coef = desc_bits // 8 zig-zag DCT
    coefficients, quantized to int8.

    Provable no-clipping property: with an orthonormal DCT, Cauchy-Schwarz
    gives |C(u,v)| <= sqrt(B^2 * 128^2) = 128*B. For B=8 that is 1024. The DC
    step of 8 gives 1024/8 = 128, exactly filling int8's range; every AC step
    is >= 10, so 1024/10 = 102.4 < 127. No retained coefficient can ever
    clip, for any 8-bit input -- the clip() below is purely defensive, and
    the self-check asserts n_clipped == 0.
    """
    assert np.all(blocks_msb & 0x03 == 0)
    K, B, _ = blocks_msb.shape

    if variant == "A":
        n_coef = desc_bits // 8
        # Explicit guard, matching the one Variant B already had. Without it, B=16
        # asks for 60 coefficients from a 16-entry DELTA_ZZ and dies with an opaque
        # "operands could not be broadcast together with shapes (1024,60) (16,)".
        # Not reachable through the shipped pipeline (the demo offers only 8 and 4,
        # and run_experiments.py uses only those), but an unguarded internal broadcast
        # error is a poor failure mode for a research artefact someone may extend.
        # ponytail: DELTA_ZZ has 16 entries because B in {4, 8} needs at most 12.
        # To support B=16, extend the table with the remaining JPEG-50 zig-zag steps.
        if n_coef > len(DELTA_ZZ):
            raise ValueError(
                f"Variant A needs {n_coef} quantization steps for block={B} "
                f"(desc_bits={desc_bits}) but DELTA_ZZ defines only {len(DELTA_ZZ)}; "
                f"supported block sizes: 4, 8")
        X = blocks_msb.astype(np.float64) - 128.0  # level shift
        D = dct_matrix(B)
        C = D @ X @ D.T  # (B,B) @ (K,B,B) @ (B,B) broadcasts over the stack
        zz = zigzag_indices(B)[:n_coef]
        rows = [r for r, _ in zz]
        cols = [c for _, c in zz]
        coef = C[:, rows, cols]  # (K, n_coef)
        # np.rint (round-half-to-even), NOT np.round-on-python-floats and
        # NOT int() truncation: truncation biases every coefficient toward
        # zero and quietly costs ~1 dB of recovered PSNR.
        raw = np.rint(coef / DELTA_ZZ[:n_coef])
        # int8's range is ASYMMETRIC: -128..127. The old test was
        # `np.abs(raw) > 127`, which flagged raw == -128 as clipped even though
        # np.clip(-128, -128, 127) is a no-op and no data is lost. Found in
        # adversarial review: it fired 387 times across the real 32-image corpus at
        # the paper's main configuration (pepper 138, splash 191, several Kodak),
        # every one of them exactly -128 -- an exactly-black 8x8 MSB block gives a DC
        # term of precisely -128. Pure counting bug, zero real data loss, but it made
        # the docstring's "provable no-clipping" claim false as stated, and NEITHER
        # payload.py's nor embed.py's self-check could catch it because their test
        # images (random noise; gradient+sinusoid+noise) never contain a flat black
        # block. The self-check asserting n_clipped == 0 was therefore asserting
        # something it structurally could not disprove.
        n_clipped = int(np.count_nonzero((raw > 127) | (raw < -128)))
        q = np.clip(raw, -128, 127).astype(np.int8)
        # Two's complement round-trips for free through the byte view --
        # that's the whole sign-handling decision: no sign-magnitude, no
        # offset binary, no explicit sign bit.
        bits = np.unpackbits(q.view(np.uint8).reshape(K, n_coef), axis=1)
        return bits, n_clipped

    if variant == "B":
        G = B // 2
        n_mean = G * G
        if desc_bits % n_mean != 0:
            raise ValueError(
                "Variant B requires desc_bits divisible by (block//2)**2; supported block: 4, 8")
        bits_per = desc_bits // n_mean
        shift = 8 - bits_per
        # Exact: every value in blocks_msb is a multiple of 4, so the sum of
        # any 4 of them is a multiple of 4 and the mean is an exact integer
        # -- no rounding error from the division itself.
        mu = blocks_msb.reshape(K, G, 2, G, 2).mean(axis=(2, 4))
        mu = np.floor(mu).astype(np.int16).reshape(K, n_mean)  # 0..252
        q = (mu >> shift).astype(np.uint8)  # B=8: 0..63 (6 bits)
        bits = np.unpackbits(q.reshape(K, n_mean, 1), axis=2)[:, :, shift:].reshape(K, desc_bits)
        return bits, 0
        # ponytail: B in {4, 8} is what the ablation needs. B=16 would need
        # a ragged 7.5-bit field (n_mean=64 into desc_bits that don't divide
        # evenly) -- add a variant-B2 layout only if that combination is
        # ever actually required.

    if variant == "C":
        _c_check(B, desc_bits)
        X = blocks_msb.astype(np.float64) - 128.0
        D = dct_matrix(B)
        zz = zigzag_indices(B)
        coef = (D @ X @ D.T)[:, [r for r, _ in zz], [c for _, c in zz]]  # (K, 64)

        # Mode decision measured in PIXEL space, not coefficient space. The
        # reconstruction path ends in rint -> clip(0,255) -> & 0xFC, and none of
        # those three are linear, so coefficient-domain error is only a proxy.
        # Reconstructing both ways and comparing against the actual target block
        # costs one extra vectorized IDCT over the stack and makes the choice
        # exactly optimal instead of nearly optimal.
        target = blocks_msb.astype(np.int32)
        cand = []
        for mode in (0, 1):
            q, deq, nsat = _c_quantize(coef, mode)
            recon = _c_idct(deq, B)
            err = ((recon.astype(np.int32) - target) ** 2).sum(axis=(1, 2))
            cand.append((q, nsat, err))
        chosen = np.argmin(np.stack([c[2] for c in cand]), axis=0)  # (K,) 0 or 1

        # Pack both ways and select rows. Two (K, 96) uint8 arrays is under a
        # megabyte at K=4096 -- cheaper than the index gymnastics of packing
        # each mode's subset in place.
        bits = np.where(chosen[:, None] == 1, _c_pack(cand[1][0], 1),
                        _c_pack(cand[0][0], 0))
        n_sat = int(np.take_along_axis(
            np.stack([c[1] for c in cand]), chosen[None, :], axis=0).sum())
        return bits, n_sat

    raise ValueError(f"unknown variant {variant!r}")


def decode_descriptor(desc: np.ndarray, variant: str, block: int) -> np.ndarray:
    """(K, desc_bits) bits -> (K, block, block) uint8 reconstructed, LSBs zeroed."""
    B = block
    K, desc_bits = desc.shape

    if variant == "A":
        n_coef = desc_bits // 8
        q = np.packbits(desc.reshape(K, n_coef, 8), axis=2).reshape(K, n_coef).view(np.int8)
        zz = zigzag_indices(B)[:n_coef]
        rows = [r for r, _ in zz]
        cols = [c for _, c in zz]
        Cz = np.zeros((K, B, B), dtype=np.float64)
        Cz[:, rows, cols] = q.astype(np.float64) * DELTA_ZZ[:n_coef]
        D = dct_matrix(B)
        Xr = D.T @ Cz @ D  # inverse transform
        recon = np.clip(np.rint(Xr + 128.0), 0, 255).astype(np.uint8)
        return recon & 0xFC

    if variant == "B":
        G = B // 2
        n_mean = G * G
        if desc_bits % n_mean != 0:
            raise ValueError(
                "Variant B requires desc_bits divisible by (block//2)**2; supported block: 4, 8")
        bits_per = desc_bits // n_mean
        shift = 8 - bits_per
        packed = np.zeros((K, n_mean, 8), dtype=np.uint8)
        packed[:, :, shift:] = desc.reshape(K, n_mean, bits_per)
        q = np.packbits(packed, axis=2).reshape(K, n_mean)
        # .astype(np.int16) BEFORE the left shift is MANDATORY: uint8(63) <<
        # 2 wraps in NumPy 2 (result would truncate back into 8 bits before
        # the += below), silently corrupting every reconstructed pixel.
        recon_mu = (q.astype(np.int16) << shift) + (1 << (shift - 1))  # bucket midpoint
        recon_mu = recon_mu.reshape(K, G, G)
        recon = np.repeat(np.repeat(recon_mu, 2, axis=1), 2, axis=2)
        recon = np.clip(recon, 0, 255).astype(np.uint8)
        return recon & 0xFC

    if variant == "C":
        _c_check(B, desc_bits)
        mode = desc[:, 0]
        # Decode under both tables and select, rather than branching per block:
        # the table a block used is data, so a Python loop over K would be the
        # only alternative, and K is 4096-16384 per channel.
        both = np.stack([_c_idct(_c_unpack(desc, m), B) for m in (0, 1)])
        return np.where(mode[:, None, None] == 1, both[1], both[0])

    raise ValueError(f"unknown variant {variant!r}")

    # Both decoders mask output with & 0xFC: the reconstruction target is
    # MSB(original), whose LSBs are already zero, so masking is consistent
    # with the target rather than a loss -- and it also guarantees a
    # recovered region deterministically fails re-authentication (a project
    # requirement, not an accident).


# --------------------------------------------------------------------------
# Bit / pixel plumbing
# --------------------------------------------------------------------------

def bits_to_lsb_pairs(bits: np.ndarray) -> np.ndarray:
    """(K, 2*B*B) bits -> (K, B*B) uint8 in 0..3; the earlier bit of each pair has weight 2.

    Payload bit index t maps to pixel p = t // 2 in raster order within the
    block (p = row*B + col). No overflow is possible when embedding, since
    MSB(x) <= 252 and pair <= 3, so MSB(x) | pair <= 255 -- which is why
    embedding is exactly invertible on the MSB plane.
    """
    return 2 * bits[:, 0::2] + bits[:, 1::2]


def lsb_pairs_from_blocks(blocks: np.ndarray) -> np.ndarray:
    """(K, B, B) -> (K, B*B) uint8 in 0..3: the two LSBs of each pixel, raster order."""
    K, B, _ = blocks.shape
    return (blocks & 0x03).reshape(K, B * B)


def lsb_pairs_to_bits(pairs: np.ndarray) -> np.ndarray:
    """Inverse of bits_to_lsb_pairs."""
    K, P = pairs.shape
    bits = np.empty((K, 2 * P), dtype=np.uint8)
    bits[:, 0::2] = (pairs >> 1) & 1
    bits[:, 1::2] = pairs & 1
    return bits


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------

if __name__ == "__main__":
    rng = np.random.default_rng(0)

    # geometry / partitioning
    x = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
    assert np.array_equal(from_blocks(to_blocks(x, 8), (64, 64), 8), x)
    assert np.array_equal(to_blocks(x, 8)[3], x[0:8, 24:32])  # block 3 == row 0, col 3
    assert zigzag_indices(8)[:6] == [(0, 0), (0, 1), (1, 0), (2, 0), (1, 1), (0, 2)]
    assert zigzag_indices(4)[:4] == [(0, 0), (0, 1), (1, 0), (2, 0)]

    # MSB projection: idempotent, only clears bits
    assert np.array_equal(msb(msb(x)), msb(x))
    assert np.all(msb(x) <= x) and np.all(x.astype(np.int16) - msb(x).astype(np.int16) <= 3)

    # DCT
    D = dct_matrix(8)
    assert np.allclose(D @ D.T, np.eye(8))
    Xf = rng.normal(size=(5, 8, 8))
    assert np.allclose(D.T @ (D @ Xf @ D.T) @ D, Xf)
    assert abs((D @ np.full((8, 8), 100.0) @ D.T)[0, 0] - 800.0) < 1e-9  # DC == B * mean

    # bit plumbing round-trips exactly
    bits = rng.integers(0, 2, (7, 128)).astype(np.uint8)
    assert np.array_equal(lsb_pairs_to_bits(bits_to_lsb_pairs(bits)), bits)

    # budget
    assert budget(8) == (128, 32, 96) and budget(4) == (32, 16, 16)

    # descriptors: exact bit width, no clipping, MSB-clean output, Variant B idempotent
    #
    # The block stack deliberately includes the EXTREME cases, not just random noise.
    # A random-only fixture cannot reach the int8 range boundaries, and that is exactly
    # how the old `abs(raw) > 127` clipping test survived: an all-black block gives a DC
    # term of precisely -128, which is a valid int8 value, and the flawed test counted
    # it as clipped. It fired 387 times on the real corpus and zero times here. Any
    # assertion that something is provably zero has to be handed the inputs that would
    # disprove it.
    for variant in ("A", "B"):
        for B in (4, 8):
            cap, tb, db = budget(B)
            blk = np.concatenate([
                msb(rng.integers(0, 256, (50, B, B), dtype=np.uint8)),   # random
                np.zeros((1, B, B), dtype=np.uint8),                      # all black -> DC = -128
                np.full((1, B, B), 252, dtype=np.uint8),                  # all white (MSB-clean)
                msb(np.full((1, B, B), 128, dtype=np.uint8)),             # flat mid-grey
            ])
            n = blk.shape[0]
            d, nclip = encode_descriptor(blk, variant, db)
            assert d.shape == (n, db) and d.dtype == np.uint8 and set(np.unique(d)) <= {0, 1}
            assert nclip == 0, (variant, B, nclip)
            r = decode_descriptor(d, variant, B)
            assert r.shape == (n, B, B) and np.all(r & 0x03 == 0)
            if variant == "B":
                assert np.array_equal(encode_descriptor(r, "B", db)[0], d)

    # ---------------- variant C ----------------
    # The bit-level round-trip is the assertion that matters most here. Variant A
    # gets its sign handling free from int8's byte view; C packs 33-34 fields of
    # 2-8 bits each by hand, so a single off-by-one in an offset or a botched
    # sign-extension would corrupt every recovered block while still producing
    # plausible-looking output. Every field is therefore exercised at BOTH ends of
    # its signed range and at zero, not at random values.
    for mode in (0, 1):
        widths = C_BITS[mode]
        # Four rows per field: most-negative, -1, 0, most-positive.
        q = np.zeros((4, 64), dtype=np.int64)
        for i, w in enumerate(widths):
            if not w:
                continue
            q[:, i] = [-(1 << (w - 1)), -1, 0, (1 << (w - 1)) - 1]
        packed = _c_pack(q, mode)
        assert packed.shape == (4, C_DESC_BITS)
        assert set(np.unique(packed)) <= {0, 1}
        assert np.all(packed[:, 0] == mode)                     # mode bit written
        back = _c_unpack(packed, mode)
        for i, w in enumerate(widths):
            expect = q[:, i] * (C_STEPS[mode][i] if w else 0.0)
            assert np.allclose(back[:, i], expect), (mode, i, w, back[:, i], expect)
    print("payload.py: variant C bit packing round-trips at every field's signed extremes")

    capC, tbC, dbC = budget(8)
    blkC = np.concatenate([
        msb(rng.integers(0, 256, (60, 8, 8), dtype=np.uint8)),      # detailed
        np.zeros((1, 8, 8), dtype=np.uint8),                        # all black
        np.full((1, 8, 8), 252, dtype=np.uint8),                    # all white
        msb(np.full((1, 8, 8), 128, dtype=np.uint8)),               # flat mid-grey
        msb(np.repeat(np.linspace(0, 255, 8, dtype=np.uint8)[None, :], 8, 0)[None]),  # ramp
    ])
    dC, nsatC = encode_descriptor(blkC, "C", dbC)
    assert dC.shape == (blkC.shape[0], 96) and set(np.unique(dC)) <= {0, 1}
    rC = decode_descriptor(dC, "C", 8)
    assert rC.shape == blkC.shape and np.all(rC & 0x03 == 0)
    # Saturation is EXPECTED and optimal for C (see the C_BITS commentary) -- the
    # check is that it is reported as a number, not that it is zero.
    assert isinstance(nsatC, int) and nsatC >= 0
    # Both tables must actually get used across a mixed stack; if the mode
    # decision were stuck, C would silently degrade to a single-table variant and
    # every measured gain in the commentary above would be wrong.
    assert set(np.unique(dC[:, 0])) == {0, 1}, "mode decision is stuck on one table"
    # The whole point of C: it must beat A on the same blocks. Flat blocks are a
    # tie by construction, so compare on the detailed ones.
    dA, _ = encode_descriptor(blkC, "A", dbC)
    rA = decode_descriptor(dA, "A", 8)
    seA = ((rA[:60].astype(np.int32) - blkC[:60].astype(np.int32)) ** 2).mean()
    seC = ((rC[:60].astype(np.int32) - blkC[:60].astype(np.int32)) ** 2).mean()
    assert seC < seA, (seC, seA)
    print(f"payload.py: variant C beats A on the same blocks "
          f"(MSE {seC:.1f} vs {seA:.1f}), saturations={nsatC}, "
          f"modes used={sorted(set(np.unique(dC[:, 0]).tolist()))}")

    # C is a block=8 format and must refuse other widths loudly, not mis-pack.
    for bad_block, bad_bits in ((4, 16), (8, 64)):
        try:
            encode_descriptor(msb(rng.integers(0, 256, (2, bad_block, bad_block),
                                               dtype=np.uint8)), "C", bad_bits)
            raise SystemExit(f"expected ValueError for variant C at block={bad_block}")
        except ValueError:
            pass

    # tag: five separate one-bit-change sensitivity asserts, plus LSB-blindness
    KEY = b"key-one"
    KEY2 = b"key-two"
    blk8 = msb(rng.integers(0, 256, (16, 8, 8), dtype=np.uint8))
    t0 = block_tags(blk8, KEY, b"ID", (64, 64), 8, 0, "A", 32)
    assert not np.array_equal(t0[0], t0[1])                                               # index binding
    assert not np.array_equal(t0, block_tags(blk8, KEY, b"IE", (64, 64), 8, 0, "A", 32))   # ID binding
    assert not np.array_equal(t0, block_tags(blk8, KEY, b"ID", (64, 64), 8, 1, "A", 32))   # channel binding
    assert not np.array_equal(t0, block_tags(blk8, KEY, b"ID", (64, 64), 8, 0, "B", 32))   # variant binding
    assert not np.array_equal(t0, block_tags(blk8, KEY, b"ID", (64, 64), 8, 0, "C", 32))   # ... incl. C
    assert not np.array_equal(t0, block_tags(blk8, KEY2, b"ID", (64, 64), 8, 0, "A", 32))  # key binding
    blk2 = blk8.copy()
    blk2[0, 0, 0] ^= 0x04  # flip an MSB-plane bit
    assert not np.array_equal(t0[0], block_tags(blk2, KEY, b"ID", (64, 64), 8, 0, "A", 32)[0])
    blk3 = blk8.copy()
    blk3[0, 0, 0] |= 0x03  # flip LSBs only
    assert np.array_equal(t0, block_tags(msb(blk3), KEY, b"ID", (64, 64), 8, 0, "A", 32))

    print("payload.py self-check OK")
