# Project Work-I report

`Project_Report.docx` is the submission copy; `Project_Report.pdf` is the
LibreOffice render used to check pagination. Both are generated — edit the
sources in `src/`, not the `.docx`.

```
python src/make_figs.py      # redraws all 21 black-and-white figures
python src/build_report.py   # two-pass build: lay out, measure, fill the TOC
```

`src/build_report.py` builds the document twice. The first pass lays it out with
placeholder page numbers, converts to PDF through LibreOffice and reads the real
page of every chapter, section, figure and table back out; the second pass writes
those numbers into the table of contents and the lists of figures and tables. The
body is its own Word section with its own page counter, so nothing in the front
matter can move a body page number between the passes. The build prints the drift
between the two passes and it must be `none`.

Numbers are not typed into the prose. `src/tables.py` reads `output/runs.csv` at
build time, and `src/FACTS.md` is the frozen fact sheet every chapter was written
against, so the report cannot drift from the measured grid.

Formatting follows `Project_Report_Format_SEM_I_2019_Course.doc`: A4, Times New
Roman 12 pt justified at 1.5 spacing, 37/23.4/23.4/32 mm margins, chapter titles
bold 14 pt upper case centred, figure captions below at 12 pt, the ADYPSOE footer
and a centred page number on every page, small roman front matter and arabic
numbering restarting at 1 from the introduction.

Chapters 1-7 run to 48 pages against the format's 30-40. Fill the student and
guide placeholders before printing, and attach the plagiarism report at
Appendix C.
