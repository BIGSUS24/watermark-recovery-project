# Research Findings — Watermark-Guided Tamper Localization and Recovery

**Date of research:** 11 August 2026
**Purpose:** Verify every citation, check whether our design is actually novel, find realistic target numbers, and identify what must be corrected in the IEEE paper before submission.

**Bottom line up front:** the project is still solid and worth building, but **three claims in the current draft paper are wrong or overstated and must be fixed.** Details in Section 5. The good news: our two riskiest design decisions turned out to be exactly what the security literature recommends, and we now know the real numbers our results have to land near.

---

## 1. Verified citations (all confirmed, no longer "[VERIFY BEFORE SUBMISSION]")

Every citation below was checked against the publisher record or an authoritative index (IEEE Xplore, SPIE Digital Library, dblp, ScienceDirect, Springer). These are now safe to use.

| Key | Full verified citation |
|---|---|
| `fridrich1999selfcorrecting` | J. Fridrich and M. Goljan, "Images with self-correcting capabilities," in *Proc. IEEE Int. Conf. Image Processing (ICIP'99)*, vol. 3, 1999, pp. 792–796. |
| `holliman2000counterfeiting` | M. Holliman and N. Memon, "Counterfeiting attacks on oblivious block-wise independent invisible watermarking schemes," *IEEE Trans. Image Processing*, vol. 9, no. 3, pp. 432–441, 2000. DOI: 10.1109/83.826780 |
| `linchang2000` **(was mislabelled 2001)** | C.-Y. Lin and S.-F. Chang, "Semi-fragile watermarking for authenticating JPEG visual content," in *Proc. SPIE 3971, Security and Watermarking of Multimedia Contents II*, 2000, pp. 140–151. DOI: 10.1117/12.384968 |
| `fridrich2002security` | J. Fridrich, "Security of fragile authentication watermarks with localization," in *Proc. SPIE 4675, Security and Watermarking of Multimedia Contents IV*, 2002, pp. 691–700. DOI: 10.1117/12.465330 |
| `lin2005hierarchical` | P.-L. Lin, C.-K. Hsieh, and P.-W. Huang, "A hierarchical digital watermarking method for image tamper detection and recovery," *Pattern Recognition*, vol. 38, no. 12, pp. 2519–2529, 2005. |
| `zhang2008errorfree` **(title was wrong in our draft)** | X. Zhang and S. Wang, "Fragile watermarking with error-free restoration capability," *IEEE Trans. Multimedia*, vol. 10, no. 8, pp. 1490–1499, 2008. |
| `zhang2011reference` | X. Zhang, S. Wang, Z. Qian, and G. Feng, "Reference sharing mechanism for watermark self-embedding," *IEEE Trans. Image Processing*, vol. 20, no. 2, pp. 485–495, 2011. |
| `korus2013efficient` | P. Korus and A. Dziech, "Efficient method for content reconstruction with self-embedding," *IEEE Trans. Image Processing*, vol. 22, no. 3, 2013. DOI: 10.1109/TIP.2012.2227769 |

**Correction found:** our draft cited a Zhang & Wang 2008 paper with the title *"Fragile watermarking scheme with extensive content restoration capability."* That is a **different paper** — Zhang, Wang & Feng, IWDW 2009, LNCS vol. 5703. The 2008 *IEEE Trans. Multimedia* paper is titled *"Fragile watermarking with error-free restoration capability."* Both are real; the draft merged them. Must be separated.

**Correction found:** Lin & Chang's semi-fragile paper is **2000**, not 2001. Our bibliography key `linchang2001` and the in-text year are both wrong.

---

## 2. New literature we did not know about — and must now cite

This is the important part. The field moved since the classics, in two separate directions.

### 2a. The exact problem our critique panel "discovered" already has a standard name

Our three-agent critique flagged the scenario where a block **and** the block holding its backup are damaged by the same edit. We were calling this "partner-block collision."

**The literature calls this the "tamper coincidence problem."** It is a named, actively-researched problem with a dedicated line of work:

- **A. Aminuddin and F. Ernawan, "AuSR1: Authentication and self-recovery using a new image inpainting technique with LSB shifting in fragile image watermarking,"** *Journal of King Saud University – Computer and Information Sciences*, 2022. DOI: 10.1016/j.jksuci.2022.02.004
- **A. Aminuddin and F. Ernawan, "AuSR2: Image watermarking technique for authentication and self-recovery with image texture preservation,"** *Computers and Electrical Engineering*, vol. 102, art. 108207, 2022. DOI: 10.1016/j.compeleceng.2022.108207
- **A. Aminuddin and F. Ernawan, "AuSR3: A new block mapping technique for image authentication and self-recovery to avoid the tamper coincidence problem,"** *Journal of King Saud University – Computer and Information Sciences*, vol. 35, no. 9, art. 101755, 2023.
- **A. Aminuddin, F. Ernawan, D. Nincarean, A. Amrullah, and D. Ariatmanto, "TCBR and TCBD: Evaluation metrics for tamper coincidence problem in fragile image watermarking,"** *Engineering Science and Technology – An International Journal*, vol. 56, art. 101790, 2024.

**What this means for us:**

1. **We must use the standard term.** Writing "partner-block collision" as if it were our own coinage, when a named problem with dedicated papers exists, is exactly the thing a reviewer or an external examiner finds in five minutes. Use "tamper coincidence problem" and cite AuSR3.
2. **AuSR3 already solves it the same way we planned to** — by mapping each block's recovery data to "the most distant location possible." Our "minimum spatial separation constraint" is the same idea. **This is no longer a novelty claim.** It is now correctly framed as: *we adopt the established distant-mapping approach, implemented as a single-cycle permutation with an enforced separation floor.*
3. **Our "recoverability rate ρ" metric may be a reinvention.** The 2024 TCBR/TCBD paper defines published metrics for precisely the quantity ρ measures (what fraction of tampered content is actually recoverable, given coincidence losses). We must either (a) adopt TCBR/TCBD and cite them, or (b) keep ρ but explicitly state its relationship to TCBR/TCBD and why we define it differently. Silently presenting ρ as novel is not defensible.

### 2b. Learned (deep-learning) watermarking for localization *and* recovery now exists

Our draft's framing — "existing detectors only detect, we detect and recover" — is **no longer true**. Recent proactive-watermarking work does both:

- **X. Zhang, R. Li, J. Yu, Y. Xu, W. Li, and J. Zhang, "EditGuard: Versatile image watermarking for tamper localization and copyright protection,"** *CVPR 2024*. arXiv:2312.08883. Reports **>95% localization precision** and near-100% copyright bit accuracy.
- **RecoverMark: Robust watermarking for localization and recovery of manipulated faces** (2026) — invertible neural network, joint immunization + recovery, high-fidelity content recovery.
- **DeepMark: A proactive deep learning-based watermarking model for tamper detection and localization across images and videos**, *Information Processing & Management*, 2026. Variable payloads 32–512 bits, tamper classifier AUC reported at 100%.
- **StableGuard** (2025) and **FractalForensics** (2025) — watermarking inside latent diffusion models / fractal watermarks for deepfake localization.
- **A Novel Self-Recovery Fragile Watermarking Scheme Based on Convolutional Autoencoder**, *Electronics*, vol. 14, no. 18, art. 3595, 2025 — a learned autoencoder generating both authentication and recovery payloads.

**What this means for us:** the novelty claim must move. See Section 5.

### 2c. Recent classical (non-learned) baselines we can compare against honestly

- **Q. Wu, H. Li, M. Li, and M. Wang, "Multi-feature fragile image watermarking algorithm for tampering blind-detection and content self-recovery,"** *Computers, Materials & Continua*, 2025. DOI: 10.32604/cmc.2025.068220. Watermarked PSNR and recovered PSNR **both > 41 dB**; false-positive and false-negative rates **0%**, tamper detection rate **100%** across tested conditions; recovered PSNR **stays above 30 dB at a 50% tamper rate**.
- **A robust fragile watermarking approach for image tampering detection and restoration utilizing hybrid transforms**, *Scientific Reports*, 2025 (Schur decomposition + DWT, semi-blind, key-only extraction).
- **Fragile watermarking for tamper localization and self-recovery based on AMBTC and VQ**, *Electronics*, vol. 12, no. 2, art. 415, 2023.
- **A recent survey of self-embedding fragile watermarking scheme for image authentication with recovery capability,** *EURASIP Journal on Image and Video Processing*, 2019. DOI: 10.1186/s13640-019-0462-3 — the canonical survey; cite it as the field overview. It establishes the standard three-axis evaluation: **transparency, tamper detection, content recovery** — which is exactly the three-part structure we already use, so our evaluation design is conventional and defensible.

---

## 3. Our two riskiest design decisions were both validated

### 3a. Keyed HMAC instead of a plain content hash — confirmed necessary

There is a published **attack paper** on exactly the weakness we designed around:

- **"Security analysis of a self-embedding fragile image watermark scheme,"** arXiv:1812.11735 — breaks a published self-embedding scheme (Qin et al., 2016) and lets an attacker modify content while still passing verification.

The paper names the root causes precisely:
- watermark computed from block content only, with no key material;
- block-independent embedding;
- deterministic, publicly recomputable hashes.

And its recommended countermeasures are, verbatim in substance, our design: **keyed hash functions, cryptographic key integration in watermark generation, and block interdependence.** Independent confirmation exists elsewhere too — the literature notes that schemes embedding authentication bits only into the corresponding block are vulnerable to collage attacks, and that the fix is a **block mapping relationship constructed from a secret key**.

**Verdict: our HMAC-SHA256 tag bound to block index + image-level identifier is the correct, literature-supported choice.** Keep it, and now we can cite *why* rather than asserting it.

### 3b. Our analytical distortion bound is correct

Our paper derives a maximum watermarked-image PSNR of **≈44.15 dB** for 2-LSB embedding. Independent reported values confirm this is right:
- Average measured PSNR for 2-LSB fragile schemes: **43.65 dB**
- Reported range across schemes: **42.6 – 46 dB**
- AuSR1 reaches **45.57 dB** using an *LSB-shifting* trick that reduces pixel intensity variation rather than plain LSB replacement.

**Verdict: the bound is sound.** Also note the optional upgrade: LSB shifting buys ~1.4 dB over naive replacement for very little code. Worth considering, not required.

---

## 4. Realistic target numbers (what our results MUST land near)

Critical for credibility. If our measured numbers fall far outside these ranges, we have a bug — not a breakthrough.

| Quantity | Realistic range from literature | Our target |
|---|---|---|
| Watermarked image PSNR (2-LSB) | 42.6 – 46 dB (mean ≈ 43.7 dB); theoretical max ≈ 44.15 dB | **43.5 – 44.2 dB** |
| Watermarked image SSIM | ≈ 0.99 or higher | **> 0.99** |
| Tamper detection rate (keyed block schemes) | 100% at block granularity is routinely reported | **~100% block-level TDR** |
| False positive / false negative rate | 0% commonly reported for keyed schemes | **≈ 0%** |
| Recovered PSNR @ ≤10% tamper | > 40 dB (one source: 40.31 dB) | **38 – 43 dB** |
| Recovered PSNR @ ~25% tamper | mid-30s dB | **33 – 38 dB** |
| Recovered PSNR @ ~50% tamper | > 30 dB for good schemes; Korus & Dziech report **37 dB average even at 50% damage** (over 10,000 images) | **30 – 35 dB** |
| Beyond 50% tamper | Sharp collapse — recovery data itself is destroyed (tamper coincidence) | **Expect and report the collapse honestly** |
| Recovered PSNR, weak/worst case | as low as 27.64 dB (AuSR1 worst reported) | anything **below ~27 dB signals a real problem** |

**Standard evaluation corpora used by this literature** (use these, don't invent our own set):
- **USC-SIPI** — 8 standard colour images, 512×512 (Lena, Peppers, Baboon, Airplane, Splash, House, Tiffany, Boat)
- **Kodak PCD0992** — 24 colour images, 512×768
- **UCID** — 1,338 colour images, 512×384

Our draft's plan of "40 images at 512×512" is fine but unconventional. **Recommendation: USC-SIPI (8 images) for the per-image comparison tables — because every competing paper reports per-image numbers on exactly these — plus Kodak (24 images) for the averaged results.** That makes our tables directly comparable to AuSR1/AuSR3/Wu 2025 instead of incomparable.

There is also a **public results repository** (`github.com/girfa/AuSRResults`) containing the AuSR algorithms' raw per-image PSNR/SSIM CSVs on USC-SIPI, Kodak, and UCID. This is a legitimate, citable source of comparison numbers we do not have to re-implement anything to obtain.

---

## 5. What must change in the IEEE paper — action list

### MUST FIX (accuracy / academic integrity)

1. **Kill the "detection-only prior art" framing.** It is factually wrong as of 2024–2026. Replace with the honest positioning below.
2. **Rename "partner-block collision" to "tamper coincidence problem"** throughout, and cite AuSR3 (2023).
3. **Demote the minimum-separation mapping from "our contribution" to "established approach, our implementation."** AuSR3 got there first.
4. **Reconcile ρ against TCBR/TCBD (2024).** Either adopt those metrics, or keep ρ and explicitly state the relationship. Do not present it as novel without addressing them.
5. **Fix the Zhang & Wang 2008 citation** (title belongs to a different paper — see Section 1).
6. **Fix Lin & Chang year: 2000, not 2001.**
7. **Remove all remaining `[VERIFY CITATION DETAILS BEFORE SUBMISSION]` markers** — every one is now resolved in Section 1.

### MUST ADD

8. **Cite the 2019 EURASIP survey** as the field overview, and use its three-axis framing (transparency / detection / recovery) explicitly — it matches what we already do.
9. **Cite arXiv:1812.11735** as the justification for keyed HMAC instead of just asserting it.
10. **Add a real comparison table** against AuSR1 (2022), AuSR3 (2023), and Wu et al. (2025) using their published numbers. We now have those numbers; there is no excuse for a comparison-free results section.
11. **Add EditGuard / DeepMark / RecoverMark to Related Work** as the learned-proactive-watermarking branch, and state the honest trade-off (their accuracy vs. our zero-training, zero-GPU, fully explainable determinism).

### HONEST WEAKNESS WE SHOULD STATE OURSELVES

12. **Our 8×8 block size gives coarser localization than the current state of the art.** AuSR1/AuSR2/AuSR3 use **2×2** blocks. An examiner comparing us to 2022–2023 work will notice immediately. Two options:
    - state the trade-off openly (8×8 = 128 bits payload capacity per block, richer recovery descriptor, coarser mask), **and/or**
    - implement a configurable block size and report 8×8 vs 4×4 as an ablation. This turns a weakness into a contribution and is cheap to build — the block size is a parameter, not a redesign.

---

## 6. Repositioned novelty claim (what we can defend)

The original claim ("we detect *and* recover, unlike detection-only work") is dead. Here is what survives scrutiny:

1. **Deterministic and fully explainable, with zero training and zero GPU.** Every verification decision reduces to a single recomputed HMAC comparison that a third party can independently re-verify. The learned methods (EditGuard, DeepMark, RecoverMark) cannot offer this — their localization is a network output, not a checkable fact. This is a genuine and defensible axis of difference, not a performance claim.
2. **A security composition stated explicitly and justified from the attack literature** — HMAC-SHA256 keyed tag bound to *both* block index and an image-level identifier, which closes the Holliman–Memon block-transplant attack and the content-only-hash forgery of arXiv:1812.11735. Many published schemes still use unkeyed or weakly-keyed hashes; we can point at the specific attacks each binding defeats.
3. **Joint, honest reporting of localization and recovery on the same axis**, including explicit accounting of unrecoverable blocks rather than excluding them from the recovery PSNR (which silently inflates it). This is a *reporting-discipline* contribution, and it must now be positioned relative to TCBR/TCBD (2024) rather than as a brand-new idea.
4. **Full reproducibility** — self-generated tampering with exact ground-truth masks, seeded and deterministic end to end, on standard public corpora, no proprietary data.

That is an honest final-year project contribution. It is not a claim to beat the state of the art on numbers, and the paper should not pretend otherwise.

---

## 7. Design decisions confirmed unchanged

Nothing found in this research invalidates the core build. These stay exactly as designed:

- 8×8 non-overlapping blocks (with the caveat in item 12 above)
- MSB-projection operator (zero the 2 LSBs) as the basis for all hashed/compressed payload, so embedding never invalidates its own payload
- 128 bits per block = 32-bit HMAC-SHA256 authentication tag + 96-bit recovery descriptor
- Recovery descriptor Variant A (quantized low-frequency DCT) and Variant B (2×2 mean-pooled averages)
- Key-seeded single-cycle permutation with enforced minimum spatial separation
- Neighbourhood refinement of the raw tamper mask before pixel-level expansion
- Explicit "unrecoverable" marking instead of fabricating content when coincidence occurs
- Four tamper classes with exact self-generated ground truth
- Pure Python / NumPy / OpenCV / hashlib, no ML, no GPU

**Conclusion: build it as designed. Fix the paper's claims and citations. We now have real target numbers to validate the implementation against, and real published baselines to compare to.**

---

## Sources

- [Fridrich & Goljan, "Images with self-correcting capabilities" (ICIP'99)](https://ws2.binghamton.edu/fridrich/Research/fridrich_icip99.doc)
- [Holliman & Memon, counterfeiting attacks (IEEE TIP 2000)](https://ieeexplore.ieee.org/document/826780/)
- [Lin & Chang, semi-fragile watermarking (SPIE 3971, 2000)](https://www.spiedigitallibrary.org/conference-proceedings-of-spie/3971/1/Semifragile-watermarking-for-authenticating-JPEG-visual-content/10.1117/12.384968.short)
- [Fridrich, security of fragile authentication watermarks with localization (SPIE 4675, 2002)](https://www.spiedigitallibrary.org/conference-proceedings-of-spie/4675/1/Security-of-fragile-authentication-watermarks-with-localization/10.1117/12.465330.short)
- [Lin, Hsieh & Huang, hierarchical watermarking (Pattern Recognition 2005)](https://dblp.org/rec/journals/pr/LinHH05.html)
- [Zhang, Wang & Feng, extensive content restoration (IWDW 2009)](https://link.springer.com/chapter/10.1007/978-3-642-03688-0_24)
- [Korus & Dziech, efficient content reconstruction (IEEE TIP 2013)](https://pkorus.pl/publications/2013-tip-se)
- [EURASIP survey of self-embedding fragile watermarking (2019)](https://jivp-eurasipjournals.springeropen.com/articles/10.1186/s13640-019-0462-3)
- [Security analysis of a self-embedding fragile image watermark scheme (arXiv:1812.11735)](https://arxiv.org/pdf/1812.11735)
- [AuSR1 (JKSU-CIS 2022) — open-access PDF](https://umpir.ump.edu.my/id/eprint/33593/1/AuSR1_Authentication%20and%20self-recovery%20using%20a%20new%20image%20inpainting.pdf)
- [AuSR2 (Computers and Electrical Engineering 2022)](https://www.sciencedirect.com/science/article/abs/pii/S0045790622004487)
- [AuSR3 — block mapping to avoid tamper coincidence (JKSU-CIS 2023)](https://www.sciencedirect.com/science/article/pii/S1319157823003099)
- [TCBR and TCBD — tamper coincidence evaluation metrics (2024)](https://www.sciencedirect.com/science/article/pii/S2215098624001769)
- [Ernawan publication list (full citations for AuSR series)](https://sites.google.com/site/ferda1902/papers)
- [AuSRResults — public per-image PSNR/SSIM data](https://github.com/girfa/AuSRResults)
- [Wu et al., multi-feature fragile watermarking (CMC 2025)](https://file.techscience.com/files/cmc/2025/online/CMC0923/TSP_CMC_68220/TSP_CMC_68220.pdf)
- [Robust fragile watermarking with hybrid transforms (Scientific Reports 2025)](https://www.nature.com/articles/s41598-025-01297-4)
- [EditGuard (CVPR 2024, arXiv:2312.08883)](https://arxiv.org/abs/2312.08883)
- [DeepMark (Information Processing & Management 2026)](https://www.sciencedirect.com/science/article/abs/pii/S0306457325005412)
- [RecoverMark (2026)](https://arxiv.org/pdf/2602.20618)
- [Self-recovery fragile watermarking with convolutional autoencoder (Electronics 2025)](https://doi.org/10.3390/electronics14183595)
- [Fragile watermarking based on AMBTC and VQ (Electronics 2023)](https://www.mdpi.com/2079-9292/12/2/415)
