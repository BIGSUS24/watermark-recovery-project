"""Variant D: fountain-coded (LT/Robust-Soliton) recovery descriptors. Phase E of
PLAN-FIXES.md -- the one research contribution in that plan, not a repair.

WHY THIS EXISTS, AND WHY IT IS NOT WHAT improvements.md ASKED FOR. improvements.md's
original ask was "replace the 1-to-1 partner map with an LT/Raptor code so any k of n
surviving blocks recover all n." That literally cannot work: payload.budget(8) gives
96 descriptor bits per block, there are n blocks and n descriptor slots, and a fountain
code needs MORE coded symbols than source symbols (~1.05n to decode n with high
probability). At rate 1 there is no redundancy to spend -- swapping the map for a
graph buys nothing.

The actual trade (Korus & Dziech) is to shrink the SOURCE symbol and spend the freed
bits on coded redundancy:
  - source symbol: a coarse 32-bit DCT descriptor per block, reusing Variant A's own
    machinery unmodified at desc_bits=32 (4 zig-zag coefficients, int8-quantized) --
    see payload.encode_descriptor's "D" branch. Not a new transform.
  - each 96-bit descriptor slot carries THREE 32-bit coded symbols -> 3n coded symbols
    for n source symbols, rate 1/3.
  - each coded symbol is the XOR of a random subset of source symbols, degree drawn
    from a Robust Soliton distribution (Luby 2002), decoded by the standard peeling
    algorithm over whichever coded symbols survived in blocks that verified authentic.
    A coded symbol living in a tampered block is ERASED, not fed a wrong value.

Expected behaviour (the point of the experiment, not a claim of victory): with
3n(1-alpha) surviving coded symbols against n unknowns, decoding should succeed while
3(1-alpha) stays above the ~1.05 overhead a peeling decoder needs, i.e. up to about
alpha ~= 0.65 -- well past the 1-to-1 map's alpha=0.5 hard collapse. But peeling
decoders fail SHARPLY, not gracefully: below threshold this can recover almost
nothing where the 1-to-1 map would still return rho = 1-alpha. Measure the cliff
honestly; do not tune the code to move it. See run_experiments.py's Phase E
comparison for the measured table.

--------------------------------------------------------------------------
KEYED GRAPH, PUBLIC PLACEMENT -- READ THIS BEFORE CHANGING build_graph/get_graph.

build_graph(key, image_id, shape, block, K) derives its keystream seed from the same
subkey() construction block_tags/build_map use, exactly like the rest of this project's
keyed constructions -- a verifier holding the key recomputes the identical graph, an
attacker without it cannot predict which source blocks feed which coded symbol.

WHERE THIS GRAPH PHYSICALLY LIVES is a SEPARATE question, already solved for free by
blockmap's existing keyed single-cycle permutation (m/minv): embed.py computes
`desc[minv]` on whatever payload.encode_descriptor("D") returns, so if row j of that
array holds coded symbols [3j, 3j+1, 3j+2], the PHYSICAL block that ends up holding
them is minv-permuted, exactly as it is for A/B/C. detect.py's existing
`desc_by_owner[ch] = stored_desc[m]` un-shuffles it back to row order for free too --
Variant D needed zero changes to blockmap.py or to embed.py's/detect.py's shuffle
logic to get a keyed, image-spread placement. That reuse is why this module never
needs `m`/`minv` itself.

THE CONTEXT-VAR PONYTAIL. embed.py's call site is frozen for this phase (A/B/C must
stay bit-for-bit unchanged) and reads:
    desc, nclip = encode_descriptor(bmsb, variant, desc_bits)
with no key parameter. payload.encode_descriptor's "D" branch therefore cannot receive
key/image_id/shape/block as normal arguments the way build_graph needs them. set_context
/ clear_context / graph_from_context exist ONLY to thread that material through this one
frozen call site -- call fountain.embed(...) (below) rather than embed.embed_image(...,
variant="D") directly, or the encode branch raises RuntimeError rather than silently
building an unkeyed graph. Not thread-safe (module-level dict, no lock) -- fine for this
single-threaded research pipeline; upgrade path is to add key/image_id parameters to
encode_descriptor directly once embed.py is back in scope for editing.
--------------------------------------------------------------------------
"""

import hmac
import struct
from collections import deque

import numpy as np

from payload import coerce_key, subkey

KEY_LABEL_FOUNTAIN = b"wgtlr/v1/fountain"
RATE = 3          # 3 coded 32-bit symbols per 96-bit descriptor slot -- see payload.D_DESC_BITS
SYMBOL_BITS = 32  # one Variant-A-style 4-coefficient DCT descriptor, per source block

# Robust Soliton defaults (Luby 2002) -- NOT fit to this corpus. Chosen once from the
# textbook recommendation and left alone: tuning these to move the measured decoding
# threshold would be exactly the "tune until it wins" PLAN-FIXES.md warns against.
RS_C = 0.03
RS_DELTA = 0.05


# --------------------------------------------------------------------------
# Deterministic keystream (same HMAC-CTR construction as blockmap._draws)
# --------------------------------------------------------------------------

def _keystream(seed: bytes):
    """Endless stream of uniform 64-bit ints: HMAC-SHA256(seed, counter) in CTR mode.

    Reimplemented locally rather than importing blockmap._draws so this module has no
    project-internal dependency beyond payload's tiny KDF helpers (payload.encode_descriptor
    lazily imports THIS module, so the reverse dependency has to stay light and acyclic).
    """
    c = 0
    while True:
        block = hmac.digest(seed, c.to_bytes(8, "big"), "sha256")
        yield from np.frombuffer(block, dtype=">u8").tolist()
        c += 1


def _sample_indices(n: int, k: int, g) -> np.ndarray:
    """k distinct uniform indices from [0, n) in O(k), via partial Fisher-Yates with a
    swap dict standing in for the untouched tail (materializing an n-length array per
    coded symbol would be O(n) each, times up to ~3*16384 coded symbols per channel --
    the O(k) form is the difference between milliseconds and minutes).
    """
    k = min(k, n)
    swaps: dict[int, int] = {}
    out = np.empty(k, dtype=np.int64)
    for i in range(k):
        j = i + (next(g) % (n - i))
        vi = swaps.get(i, i)
        vj = swaps.get(j, j)
        out[i] = vj
        swaps[j] = vi
    return out


# --------------------------------------------------------------------------
# Robust Soliton degree distribution
# --------------------------------------------------------------------------

def _robust_soliton_pmf(K: int, c: float = RS_C, delta: float = RS_DELTA) -> np.ndarray:
    """(K+1,) pmf over degree d=1..K (index 0 unused, kept for direct 1-based indexing).

    Standard Luby (2002) construction. The tau spike's asymptotics can go slightly
    negative for very small K (a handful of source symbols) -- clipped to 0 rather than
    guarded with a special case, since Variant D targets K in the hundreds-to-thousands
    range (real block counts) where this never fires; see this module's __main__ for a
    worked K=500 check.
    """
    if K == 1:
        out = np.zeros(2)
        out[1] = 1.0
        return out
    d = np.arange(1, K + 1, dtype=np.float64)
    rho = np.empty(K, dtype=np.float64)
    rho[0] = 1.0 / K
    rho[1:] = 1.0 / (d[1:] * (d[1:] - 1.0))

    S = c * np.log(K / delta) * np.sqrt(K)
    Kk = max(1, min(int(round(K / S)), K))
    tau = np.zeros(K, dtype=np.float64)
    if Kk > 1:
        tau[: Kk - 1] = S / (K * d[: Kk - 1])
    tau[Kk - 1] += S * np.log(S / delta) / K
    tau = np.clip(tau, 0.0, None)  # ponytail: tiny-K asymptotic can go negative; see docstring

    mu = rho + tau
    mu /= mu.sum()
    out = np.zeros(K + 1, dtype=np.float64)
    out[1:] = mu
    return out


# --------------------------------------------------------------------------
# Graph construction -- keyed, cached, public only in structure not in seed
# --------------------------------------------------------------------------

def build_graph(key: bytes | str, image_id: bytes, shape: tuple[int, int], block: int,
                K: int, rate: int = RATE) -> list[np.ndarray]:
    """n_coded = rate*K coded symbols; graph[c] = sorted-by-draw-order source indices
    XORed into coded symbol c. Deterministic in (key, image_id, shape, block, K, rate) --
    a verifier with the key recomputes this exactly, matching build_map's contract.
    """
    key_b = coerce_key(key)
    n_coded = rate * K
    pmf = _robust_soliton_pmf(K)
    cdf = np.cumsum(pmf)
    M, N = shape
    seed = hmac.digest(
        subkey(key_b, KEY_LABEL_FOUNTAIN),
        struct.pack(">HHHII", M, N, block, K, n_coded)
        + len(image_id).to_bytes(2, "big") + image_id,
        "sha256",
    )
    g = _keystream(seed)
    graph = []
    for _ in range(n_coded):
        # 53 bits of the 64-bit draw give a uniform double with full float64 mantissa
        # precision -- more than the CDF search needs, cheap to compute.
        u = (next(g) % (1 << 53)) / float(1 << 53)
        deg = int(np.searchsorted(cdf, u, side="right"))
        deg = max(1, min(deg, K))
        graph.append(_sample_indices(K, deg, g))
    return graph


_GRAPH_CACHE: dict = {}


def get_graph(key: bytes | str, image_id: bytes, shape: tuple[int, int], block: int,
              K: int, rate: int = RATE) -> list[np.ndarray]:
    """Cached build_graph -- pure function of its arguments, so caching is always safe.
    ponytail: unbounded process-lifetime dict; fine for a batch research run over a
    handful of images, add an LRU cap if this ever becomes a long-lived service.
    """
    key_b = coerce_key(key)
    ck = (key_b, bytes(image_id), tuple(shape), block, K, rate)
    if ck not in _GRAPH_CACHE:
        _GRAPH_CACHE[ck] = build_graph(key_b, bytes(image_id), tuple(shape), block, K, rate)
    return _GRAPH_CACHE[ck]


# --------------------------------------------------------------------------
# Context var -- threads key material through embed.py's frozen call site (see module
# docstring's CONTEXT-VAR PONYTAIL section)
# --------------------------------------------------------------------------

_CTX: dict = {}


def set_context(key: bytes | str, image_id: bytes, shape: tuple[int, int], block: int) -> None:
    _CTX.clear()
    _CTX.update(key=coerce_key(key), image_id=image_id, shape=tuple(shape), block=block)


def clear_context() -> None:
    _CTX.clear()


def graph_from_context(K: int) -> list[np.ndarray]:
    """Called only from payload.encode_descriptor's "D" branch, which embed.py invokes
    with no key of its own -- see the module docstring."""
    if not _CTX:
        raise RuntimeError(
            "encode_descriptor(variant='D') needs fountain.set_context(...) active -- "
            "call fountain.embed(img, key, image_id, block) instead of "
            "embed.embed_image(..., variant='D') directly. embed.py's encode_descriptor "
            "call site has no key parameter, so Variant D threads key material through "
            "this context instead; see fountain.py's module docstring.")
    return get_graph(_CTX["key"], _CTX["image_id"], _CTX["shape"], _CTX["block"], K)


def embed(img: np.ndarray, key: bytes | str, image_id: bytes | str, block: int = 8):
    """Variant D entry point -- identical to embed.embed_image(img, key, image_id, block,
    "D") but sets up the context payload.encode_descriptor's "D" branch needs. Use this
    instead of calling embed_image directly with variant="D".
    """
    import embed as _embed_mod          # local: keeps this module cv2/imageio-free unless used
    from payload import crop_to_blocks

    key_b = coerce_key(key)
    iid = image_id.encode("utf-8") if isinstance(image_id, str) else image_id
    shape = crop_to_blocks(img, block)[0].shape[:2]
    set_context(key_b, iid, shape, block)
    try:
        return _embed_mod.embed_image(img, key, image_id, block, "D")
    finally:
        clear_context()


# --------------------------------------------------------------------------
# Encode / decode over 0/1 bit-array symbols (payload.py's bit-array-first convention --
# XOR on a 0/1 uint8 array IS the fountain code's XOR combiner, no packing to a real
# 32-bit int needed)
# --------------------------------------------------------------------------

def encode(source_bits: np.ndarray, graph: list[np.ndarray]) -> np.ndarray:
    """(K, SYMBOL_BITS) source bit-rows + graph -> (n_coded, SYMBOL_BITS) coded bit-rows."""
    n_coded = len(graph)
    out = np.empty((n_coded, source_bits.shape[1]), dtype=np.uint8)
    for c, nbrs in enumerate(graph):
        out[c] = np.bitwise_xor.reduce(source_bits[nbrs], axis=0)
    return out
    # ponytail: a Python loop over n_coded (~3K, up to ~50K at this corpus's largest
    # images) -- same style/cost class as payload.block_tags' per-block HMAC loop.
    # Vectorize with a ragged-groupby XOR reduction if K ever grows an order of
    # magnitude past this corpus.


def decode(coded_bits: np.ndarray, erased: np.ndarray, graph: list[np.ndarray], K: int
          ) -> tuple[np.ndarray, np.ndarray]:
    """Standard LT/fountain peeling decoder.

    `erased[c]` True means the physical block holding coded symbol c failed
    authentication -- that symbol is DROPPED from the graph entirely, never fed its
    (untrustworthy) value in. "Erased, not wrong": the whole reason this is safe is
    that a tampered holder can only ever cost decodability, never inject a plausible
    wrong answer, because its value is never looked at.

    Returns (recovered, solved). `recovered[j]` is meaningful ONLY where `solved[j]` is
    True -- a source symbol the ripple never reaches is left unsolved, not guessed, so
    the caller can mark it unrecoverable rather than trusting garbage.
    """
    remaining: dict[int, set] = {}
    value: dict[int, np.ndarray] = {}
    by_source: list[list[int]] = [[] for _ in range(K)]
    for c, nbrs in enumerate(graph):
        if erased[c]:
            continue
        remaining[c] = set(int(x) for x in nbrs)
        value[c] = coded_bits[c].copy()
        for s in nbrs:
            by_source[int(s)].append(c)

    solved = np.zeros(K, dtype=bool)
    recovered = np.zeros((K, coded_bits.shape[1]), dtype=np.uint8)
    queue = deque(c for c, nb in remaining.items() if len(nb) == 1)
    while queue:
        c = queue.popleft()
        nb = remaining.get(c)
        if nb is None or len(nb) != 1:
            continue  # stale queue entry -- already resolved by another edge
        s = next(iter(nb))
        if solved[s]:
            del remaining[c]
            continue
        recovered[s] = value[c]
        solved[s] = True
        del remaining[c]
        for c2 in by_source[s]:
            nb2 = remaining.get(c2)
            if nb2 is None or s not in nb2:
                continue
            nb2.discard(s)
            value[c2] = value[c2] ^ recovered[s]
            if len(nb2) == 1:
                queue.append(c2)
            elif len(nb2) == 0:
                del remaining[c2]  # fully-known check symbol -- nothing left to solve with it
    return recovered, solved


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------

if __name__ == "__main__":
    rng = np.random.default_rng(0)
    K = 500
    KEY = b"fountain-selfcheck-key"
    IID = b"selfcheck"
    SHAPE = (200, 200)
    BLOCK = 8
    n_coded = RATE * K

    graph = build_graph(KEY, IID, SHAPE, BLOCK, K)
    assert len(graph) == n_coded
    assert all(1 <= len(nb) <= K for nb in graph)
    assert all(len(set(nb.tolist())) == len(nb) for nb in graph)  # no repeated neighbour
    print(f"fountain.py: graph built, K={K} n_coded={n_coded}, "
          f"mean degree={np.mean([len(nb) for nb in graph]):.2f}")

    # determinism: identical (key, id, shape, block, K) -> identical graph
    graph2 = build_graph(KEY, IID, SHAPE, BLOCK, K)
    assert all(np.array_equal(a, b) for a, b in zip(graph, graph2))

    # key sensitivity: a different key must give an essentially different graph -- the
    # whole point of deriving the seed from subkey(key, ...) instead of a public constant
    graph_other = build_graph(b"a-different-key", IID, SHAPE, BLOCK, K)
    same = sum(np.array_equal(a, b) for a, b in zip(graph, graph_other))
    assert same < n_coded * 0.05, f"graph barely changed under a different key ({same}/{n_coded})"
    print("fountain.py: graph is deterministic and key-sensitive")

    source = rng.integers(0, 2, size=(K, SYMBOL_BITS)).astype(np.uint8)
    coded = encode(source, graph)
    assert coded.shape == (n_coded, SYMBOL_BITS) and set(np.unique(coded)) <= {0, 1}

    # -------- above threshold: 45% of coded symbols survive -> 3*0.45=1.35 redundancy,
    # comfortably above the ~1.05 a peeling decoder needs -- full recovery expected.
    erase_frac_ok = 0.55
    erased_ok = rng.random(n_coded) < erase_frac_ok
    recovered_ok, solved_ok = decode(coded, erased_ok, graph, K)
    assert solved_ok.all(), (
        f"expected full decode at erase_frac={erase_frac_ok} "
        f"({(1 - erase_frac_ok) * RATE:.2f}x redundancy), got {solved_ok.mean():.3f} solved")
    assert np.array_equal(recovered_ok, source), "decoded values must exactly match the known source"
    print(f"fountain.py: erase_frac={erase_frac_ok} -> {solved_ok.mean() * 100:.1f}% solved, "
          "all values exact -- OK")

    # -------- below threshold: 90% erased -> 3*0.10=0.30 redundancy, far below decodable.
    # A peeling decoder fails SHARPLY (see module docstring): this must leave real gaps,
    # not degrade gracefully, and it must REPORT them rather than guess.
    erase_frac_bad = 0.90
    erased_bad = rng.random(n_coded) < erase_frac_bad
    recovered_bad, solved_bad = decode(coded, erased_bad, graph, K)
    assert not solved_bad.all(), (
        f"expected decode failure at erase_frac={erase_frac_bad} -- self-check threshold "
        "is not actually testing the below-threshold case")
    # "reports failure rather than silently returning garbage" means: whatever the decoder
    # DID claim solved is exactly right -- never that it recovers less but never that it
    # recovers WRONG.
    assert np.array_equal(recovered_bad[solved_bad], source[solved_bad])
    print(f"fountain.py: erase_frac={erase_frac_bad} -> only {solved_bad.mean() * 100:.1f}% "
          "solved, failure correctly reported for the rest (not silently guessed) -- OK")

    print("fountain.py self-check OK")
