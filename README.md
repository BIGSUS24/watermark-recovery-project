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

## Just want to use it?

**Setting this up on a new machine? Follow [INSTALL.md](INSTALL.md)** — every command
spelled out, including installing Python, with a troubleshooting section for the
things that actually go wrong.

Short version, once dependencies and the corpus are in place:

```bash
python webapp/server.py            # then open http://127.0.0.1:8765/
```

The real round trip it is built for:

1. **Protect an image** -- pick a corpus sample or upload your own PNG, embed the
   watermark, and **download the protected file**. It is also saved to a local
   library (`webapp/library.db`, SQLite) together with the key, the image identity
   bound into every HMAC, and the block geometry -- the three things without which a
   keyed fragile watermark cannot be checked again later.
2. **Edit that downloaded file** in any image editor, anywhere, and save it as PNG.
3. **Upload it under "Verify an upload."** The app works out *which* library record
   it is, compares it against the stored copy, says where it was altered, and
   offers **Repair**.

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
HTML/CSS/JS -- no build step, no CDN, no external network requests. `--port` and
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
fails.

`src/sanity_gate.py` checks `runs.csv` against bands measured from this corpus,
and `src/make_tables.py` calls it first and refuses to emit tables if it fails --
so "generate tables from numbers nobody sanity-checked" is impossible through the
intended entry point. Note its scope honestly: it validates the results CSV, not
the generated LaTeX, and a hardcoded false figure once reached a printed table
through exactly that gap.

Every module in `src/` (`payload.py`, `blockmap.py`, `embed.py`, `detect.py`,
`recover.py`, `tamper.py`, `metrics.py`, ...) is independently runnable and
carries its own self-check (`python src/<module>.py`) -- none of them require
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
