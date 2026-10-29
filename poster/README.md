# A3 project poster

One A3 poster made from seven trimmed A4 prints. An A3 sheet is exactly two A4
sheets, so whole A4 prints cannot tile it — each piece is printed centred on an A4
page with cut marks and trimmed down.

    python poster/make_poster.py              # demo assets are cached
    python poster/make_poster.py --refresh    # re-run the pipeline to rebuild them

| output | what |
| --- | --- |
| `../output/poster/Poster_A3_sheets.pdf` | page 1 assembly map, page 2 title band (A4 landscape), pages 3–8 panels 1–6 (A4 portrait) |
| `../output/poster/Poster_A3_preview.pdf` | the finished poster on a single A3 page, for checking before printing |
| `../output/poster/assets/` | the greyscale worked example and its numbers |

Layout on the A3: a 271 × 40 mm title band across the top, then a 2 × 3 grid of
132 × 111 mm panels read down the left column and then down the right. Margins are
13 mm at the edges, 7 mm between pieces.

Everything is greyscale and light on ink because it is printed black and white. The
paper's qualitative figure marks the repairable region red and the unrecoverable
subset cyan; desaturated those two land at 76 and 178 grey over a busy photograph and
stop being readable, so `build_assets()` re-runs the trial and rebuilds that mask in
print tones instead of converting the colour figure after the fact.

Numbers come from `report/src/FACTS.md`, `output/runs.csv` and that one re-run.
Nothing is typed in by hand. Each panel function returns the y it finished at and
`main()` asserts the panel did not overflow its box, so a text edit that no longer
fits fails the build instead of printing off the edge.
