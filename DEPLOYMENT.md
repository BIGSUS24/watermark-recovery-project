# Deployment Guide: What Survives, What Doesn't

This watermark lives entirely in the two least-significant bit-planes of every
pixel. Any step in an image's life that re-samples, re-quantizes, or
re-encodes those bits destroys the watermark permanently and silently -- the
file still opens, still looks right, and now authenticates as fully tampered
(or, worse, as unrecoverable) even though nobody touched the content. There is
no step in the pipeline that is "mostly fine." Every step below is marked
**SAFE** or **FATAL**; there is no middle category, because there is no partial
credit for a bit-plane.

Grounded in `src/imageio_any.py`, the module that decides what this project
will accept as a carrier for the watermark at all.

## SAFE

| Step | Why it's safe |
|---|---|
| EXIF/metadata stripping, with a metadata-only tool (e.g. `exiftool -all=`, not a re-save through an image library) | Touches header bytes only; the pixel data, and the two LSB planes inside it, are untouched. |
| Block-aligned lossless crop | A crop is safe only if both edges land on multiples of the embedding block size (8 px by default) *and* the crop is written with a lossless codec. An off-grid crop shifts every block boundary, which is equivalent to a resize for this watermark's purposes -- see FATAL below. |
| PNG round trip | PNG is lossless by format; re-saving a PNG as PNG changes no pixel value. |
| BMP round trip | Same reasoning; uncompressed, lossless. |
| TIFF round trip (uncompressed or with a lossless codec such as LZW/ZIP) | Lossless TIFF preserves pixels exactly. A TIFF saved with a lossy codec does not -- check the codec, not just the extension. |
| Lossless WebP (VP8L) | `src/imageio_any.py` sniffs the RIFF chunk id right after the `WEBP` tag: `VP8L` is genuinely lossless and is in the `LOSSLESS` set. The app accepts it for both protecting and verifying. |

## FATAL

| Step | Why it's fatal |
|---|---|
| JPEG conversion, at any point, even once, even as an intermediate/thumbnail step | JPEG's DCT quantization overwrites the LSB planes with new values derived from an 8x8 frequency transform. There is nothing left to verify afterward, and no later lossless re-save brings it back -- the information is gone, not hidden. |
| Image-CDN auto-optimisation (Cloudflare Image Resizing, Cloudinary `f_auto`/`q_auto`, imgix, Next.js Image Optimization, WordPress "compress images" plugins, and similar) | These re-encode on the fly, typically to lossy WebP or JPEG, regardless of the format the file was uploaded in. The watermark is destroyed the first time the CDN serves an optimised variant, and this usually happens invisibly to whoever is looking at the image. |
| WhatsApp media sharing | WhatsApp re-encodes images sent through the normal media picker. Sending "as a document" avoids some but not all of this in practice, and cannot be assumed safe without independently verifying the received bytes are byte-identical to what was sent -- treat WhatsApp transit as fatal by default. |
| Telegram media sharing | Same story: the photo path re-encodes. Sending as a file/document is closer to safe but still not guaranteed by the client across all cases; verify before trusting it. |
| Any resize | Resampling changes every pixel and moves every block boundary off the grid the watermark was embedded on. A shape mismatch is now explicitly rejected on verify (`webapp/server.py`'s shape gate) rather than silently misinterpreted, but the watermark is still gone -- rejection, not recovery. |
| Any rotation (including a "lossless" 90-degree rotate in a generic editor that actually resamples on save) | Same reasoning as resize: block boundaries move. A rotation that is not a true lossless pixel permutation is fatal, and most consumer tools do not guarantee the distinction, so treat all rotation as fatal. |
| Lossy WebP (`VP8`) or the `VP8X` extended container | `src/imageio_any.py` refuses both. `VP8` is lossy by format. `VP8X` can wrap either a lossless (`ALPH`+`VP8L`) or lossy (`VP8`) payload, and telling which would mean walking the whole RIFF chunk list; the module calls it lossy rather than risk a false "lossless" that would tell a caller their watermark survived when it may not have. |
| GIF | Palette quantization is lossy for anything not already a flat-colour image. |

## Before You Deploy: checklist

- [ ] **Pre-embedding is mandatory.** The watermark must be applied before the
      image is ever exposed to a lossy step -- a CDN, a messaging app, a
      resize, a JPEG save. There is no way to add authentication to an image
      after the fact if any of those already happened to it.
- [ ] **Legacy images cannot be covered retroactively.** Anything already
      distributed as a JPEG, already re-encoded by a CDN, or already put
      through WhatsApp/Telegram has already lost the bit-planes this scheme
      needs. Re-embedding a watermark into that file only protects it from
      *this point forward*; it says nothing about, and cannot prove anything
      about, what happened before.
- [ ] Keep one lossless master (PNG/BMP/TIFF/lossless WebP) all the way
      through the pipeline; never let a lossy step touch it even transiently
      (not even for a thumbnail generated from the same file).
- [ ] Turn off CDN/host auto-optimisation for any URL that serves a protected
      image, or serve protected images from a path the optimiser is
      configured to skip.
- [ ] Treat any hop through a consumer messaging app as watermark-destroying
      by default; distribute protected images through a channel that
      preserves bytes (direct download, a file-sharing link, cloud storage)
      instead.
- [ ] Never resize or rotate a protected image, in any tool, for any reason,
      before verification. If a resized/rotated copy is needed for display,
      keep it as a *separate, unprotected* derivative and verify against the
      untouched original.
- [ ] After each new step you add to a real pipeline, verify a copy through
      `detect` immediately. Catch the step that breaks it while you still
      know which step you just added, rather than after the fact with no way
      to tell which of ten steps was the one that mattered.
