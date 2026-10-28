# ICIP short paper (4–6 pages, IEEE conference format)

A second, shorter paper over the same work as `paper/IEEE_Paper.tex`, written to
the ICIP author submission guidelines: IEEE conference template, 4–6 pages,
6 keywords, abstract under 400 words, corresponding author indicated.
`paper/IEEE_Paper.tex` is untouched — this is an additional artifact, not a
replacement.

Its worked example is an author-supplied 512×512 photograph instead of the
standard USC-SIPI plate the long paper uses.

    python paper/icip/run_photo.py      # pipeline on the photograph -> figures + JSON
    python paper/icip/assemble.py       # parts/*.tex -> paper/ICIP_Paper.tex -> PDF

| path | what |
| --- | --- |
| `photo_src.jpeg` | the source capture, as supplied |
| `photo_512.png` | centre-cropped, Lanczos-resampled, lossless — the actual input |
| `photo_results.json` | 56 trials (4 tamper classes × 7 ratios × 2 variants) on it |
| `parts/` | the section files `assemble.py` stitches together |
| `../ICIP_Paper.tex` | generated; edit `parts/`, not this |
| `../../output/paper/ICIP_Paper.pdf` | the compiled paper |
| `../../output/figures/icip_*.{png,pdf}` | its two generated figures |

Every number in the paper comes from `output/runs.csv` (via `report/src/FACTS.md`)
or from `photo_results.json`. Nothing was typed in by hand.
