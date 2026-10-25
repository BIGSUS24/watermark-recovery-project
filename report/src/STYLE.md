# HOUSE STYLE AND OUTPUT PROTOCOL — read before writing a single word

You are writing part of a Bachelor of Engineering project report submitted to
Savitribai Phule Pune University through Ajeenkya DY Patil School of
Engineering, Pune, Department of Computer Engineering, academic year 2026-27.
It is a Project Work-I (Semester I) preliminary report. An internal guide, a
departmental panel and an external examiner will read it.

## Voice and register
- Formal academic English, third person. Use "the project", "the scheme", "the
  system", "this work". First person plural ("we") is acceptable sparingly in
  methodology and conclusions, as in the attached synopsis. Never "I", never "you".
- Confident and precise, never promotional. No "revolutionary", "cutting-edge",
  "state-of-the-art", "seamless", "robust solution", "leverage", "delve".
- Prefer the concrete sentence over the abstract one. Say what the system does,
  with what, and at what measured cost.
- Honesty is a graded property of this report. Where the project is weaker than
  published work, say so plainly in the same paragraph as the claim.
- British or American spelling — pick American and stay consistent.

## Paragraph shape
- Paragraphs of 70 to 140 words. Three to six paragraphs per section.
- No one-sentence paragraphs except as a deliberate hinge, at most once per chapter.
- Bulleted lists only where the content is genuinely a list (requirements,
  objectives, risks, limitations). At most two lists per chapter, each 3-8 items.
- Do not start consecutive paragraphs with the same word.

## Numbers
- Every figure, percentage, decibel value, count and date MUST come verbatim from
  FACTS.md. If FACTS.md does not contain a number you want, do not write it.
- Never quote a number from paper/Synopsis.tex — several of its prose values are
  stale. Read that file for tone, argument and technical depth only.

## Citations
Cite as a bracketed number, e.g. "passive detectors analyse the received image
alone [2], [3]". The numbering below is FIXED. Use these numbers and no others.

[1]  Fridrich & Goljan, 1999 — Protection of digital images using self-embedding
[2]  Zhou et al., 2018 — Learning rich features for image manipulation detection
[3]  Wu et al., 2019 — ManTra-Net
[4]  Wong & Memon, 2001 — Secret and public key image watermarking
[5]  Rey & Dugelay, 2002 — Survey of watermarking for image authentication
[6]  Cox et al., 1997 — Secure spread spectrum watermarking
[7]  Holliman & Memon, 2000 — Counterfeiting attacks on block-wise independent marks
[8]  Lin & Chang, 2000 — Semi-fragile watermarking for JPEG
[9]  Fridrich, 2002 — Security of fragile authentication watermarks with localization
[10] Lin et al., 2005 — Hierarchical watermarking for tamper detection and recovery
[11] Zhang et al., 2011 — Reference sharing mechanism for watermark self-embedding
[12] Korus & Dziech, 2013 — Efficient content reconstruction with self-embedding
[13] Aminuddin & Ernawan, 2022 — AuSR1
[14] Aminuddin & Ernawan, 2022 — AuSR2
[15] Aminuddin & Ernawan, 2023 — AuSR3
[16] Aminuddin et al., 2024 — TCBR and TCBD evaluation metrics
[17] Zhang et al., 2024 — EditGuard
[18] Wu et al., 2026 — Multi-feature fragile watermarking (CMC)
[19] Zhang & Wang, 2008 — Fragile watermarking with error-free restoration
[20] NIST FIPS 180-4 — Secure Hash Standard
[21] Wang et al., 2004 — SSIM
[22] USC-SIPI Image Database
[23] Kodak Lossless True Color Image Suite
[24] C2PA Content Credentials specification
[25] EURASIP, 2019 — Survey of self-embedding fragile watermarking
[26] arXiv:1812.11735, 2018 — Security analysis of a self-embedding fragile watermark

## OUTPUT PROTOCOL — follow exactly, the file is parsed by a script

Write plain UTF-8 text. No Markdown headings, no bold, no italics, no code
fences, no tables, no figures. Only these four constructs:

1. A section heading, alone on its line:
   @@SEC 5.1 System Architecture
2. A subsection heading, alone on its line:
   @@SUB 5.1.2 Stage Two: Distribution
3. A bullet, one per line, starting with "* ":
   * Python 3.10 or later, with no third-party cryptographic library.
4. Everything else is a body paragraph. Separate paragraphs with one blank line.

To place a figure or a table, put its marker alone on its own line, exactly:
   [[FIG 5.4]]
   [[TABLE 3.1]]
The build script replaces the marker with the real figure or table and its
caption. You do NOT draw figures or write tables. Place each marker at the point
in the text where the reader should look at it, normally right after the
paragraph that first discusses it, and refer to it in prose as "Fig. 5.4" or
"Table 3.1". Use every marker in your assigned list exactly once.

Mathematical notation: write it inline in plain text, e.g. "cap(B) = 2B^2",
"rho = 1 - |U|/|T|", "m(i)", "alpha". Display equations get their own line
prefixed with "@@EQ ", e.g.
   @@EQ a_i = Trunc_32( HMAC-SHA256_Ks( ID || i || MSB(b_i) || r_{m^-1(i)} ) )
Number them nowhere; the build script numbers them.

Do not write a chapter title — the build script adds it. Start your file with
your first @@SEC line.

Write to the exact output path you are given, using the Write tool, and then
stop. Report back only the word count and the section list.
