# Installation — the completely-spelled-out version

This guide assumes you know nothing. Every command is copy-paste. If something
goes wrong, the fix is in [Troubleshooting](#troubleshooting) at the bottom.

Total time: about 5 minutes, most of it waiting for downloads.

---

## Step 1 — Install Python

You need Python **3.10 or newer**. Check whether you already have it:

**Windows** — open Start, type `cmd`, press Enter, then paste:

```
python --version
```

**macOS / Linux** — open Terminal, then paste:

```
python3 --version
```

If it prints something like `Python 3.12.1`, you are done with this step. Skip to Step 2.

If it prints an error, or a version below 3.10:

- **Windows:** download from <https://www.python.org/downloads/>. Run the installer.
  **Tick the box that says "Add python.exe to PATH"** on the very first screen — this
  is the one thing people miss, and skipping it makes every later command fail.
  Then close the black window and open a new one.
- **macOS:** `brew install python` (needs [Homebrew](https://brew.sh)), or download
  from the link above.
- **Linux (Ubuntu/Debian):** `sudo apt update && sudo apt install python3 python3-pip python3-venv`

---

## Step 2 — Download this project

If you have `git`:

```
git clone https://github.com/bigsus24/watermark-recovery-project.git
cd watermark-recovery-project
```

No `git`? On the GitHub page click the green **Code** button, then **Download ZIP**.
Unzip it. Then open a terminal **inside the unzipped folder**.

> **How to open a terminal in a folder**
> - **Windows:** open the folder in File Explorer, click the address bar, type `cmd`, press Enter.
> - **macOS:** right-click the folder → Services → New Terminal at Folder.
> - **Linux:** right-click inside the folder → Open in Terminal.

Confirm you are in the right place — this must list `requirements.txt`:

```
dir          (Windows)
ls           (macOS / Linux)
```

---

## Step 3 — Make a private workspace for the libraries

This keeps the project's packages separate from the rest of your computer, so
nothing else can break. Run **both** lines, in order.

**Windows:**

```
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**

```
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should now start with `(.venv)`. That means it worked.

> You must run the activate line **every time** you open a new terminal to use this
> project. Nothing else in this guide needs repeating.

---

## Step 4 — Install the libraries

```
pip install -r requirements.txt
```

This downloads NumPy, OpenCV, Flask and a few others. Takes 1–3 minutes. Some
scrolling text is normal. You want the last line to say `Successfully installed ...`.

---

## Step 5 — Download the test images

```
python samples/fetch_corpus.py
```

This fetches 32 standard test photographs (the USC-SIPI and Kodak sets used by the
published papers this work compares against) and checks every single file against a
SHA-256 fingerprint recorded in the repository. If a download is corrupted or a
server has quietly changed a file, this stops with an error instead of carrying on
with the wrong data.

Expect `32/32 OK` at the end.

> **You only need this step if you want the built-in sample images or want to
> reproduce the paper's results.** To just protect your own photos, skip it.

---

## Step 6 — Start the app

```
python webapp/server.py
```

You will see:

```
Fragile Watermark Recovery -- open http://127.0.0.1:8765/ in your browser
```

Open **<http://127.0.0.1:8765/>** in Chrome, Edge, or Firefox.

To stop the app, click the terminal window and press `Ctrl+C`.

---

## Step 7 — Use it

The app runs entirely on your own machine. Nothing is uploaded anywhere.

### Protect a photo

1. Click **Protect an image** in the left menu.
2. Either leave **Sample image** selected, or click **Upload my own** and choose a
   **PNG** file.
3. Click **Protect this image**.
4. Click **Download protected image**.

You now have a file that looks identical to the original but carries an invisible,
tamper-evident watermark. It has also been saved into a local library, along with
the secret key needed to check it later.

### Prove that tampering gets caught

5. Open the downloaded file in **any** image editor — MS Paint is fine. Scribble on
   it, erase someone, paste something in. **Save it as PNG.**
6. Back in the app, click **Verify an upload** and drop the edited file in.
7. Click **Identify and verify**.

The app works out which library record the file is, without being told, and shows
you exactly which parts were altered.

8. Click **Repair this image** to rebuild the damaged parts.

### Fastest possible demo

Don't want to juggle files? On the **Protect an image** page, scroll to
**"Or test it right here"** — damage, detect and repair all happen on one page.

---

## Important limits (these are by design, not faults)

- **PNG only.** The watermark lives in the two least-significant bits of each pixel.
  Saving as JPEG throws those bits away. That is the price of a watermark fragile
  enough to notice a single altered pixel.
- **Only images this app protected.** There is nothing to check in a photo that was
  never watermarked. That is what the library is for.
- **Do not resize or crop** a protected file. The check works on an 8×8 grid; move
  the grid and nothing lines up.
- **Repaired areas are approximations** — a low-frequency reconstruction, visibly
  softer than the original. Never a pixel-perfect restore.
- **The library stores keys in plain text**, next to the images. Correct for a local
  personal tool. Wrong for a real deployment, where keys belong in an OS keyring or
  hardware security module and never sit beside the file they authenticate.

---

## Optional — reproduce the published results

Run in this order. Each step needs the previous one.

```
python src/test_e2e.py             # ~2 min   correctness gate. If this fails, trust nothing below.
python src/run_experiments.py      # HOURS    the full 1,184-run experiment grid
python src/sanity_gate.py          # instant  must print "overall: PASS"
python src/make_tables.py          # instant  writes output/tables/*.tex
python src/plots.py                # ~1 min   writes output/figures/
```

In a hurry? `python src/run_experiments.py --quick` does 10 runs instead of 1,184.

Every module checks itself in isolation too:

```
python src/payload.py
python src/blockmap.py
python src/embed.py
python src/detect.py
python webapp/db.py
```

---

## Troubleshooting

**`python: command not found` / `'python' is not recognized`**
Python is not installed, or was installed without "Add to PATH". On Windows,
reinstall and tick that box. On macOS/Linux, try `python3` instead of `python`.

**`pip: command not found`**
Use `python -m pip install -r requirements.txt` instead.

**`.venv\Scripts\activate` fails on Windows PowerShell with a script-execution error**
Either use `cmd` instead of PowerShell, or run this once:
```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**`Address already in use` / `port 8765 is already in use`**
Something else has that port. Pick another:
```
python webapp/server.py --port 9000
```
Then open <http://127.0.0.1:9000/>.

**The page won't load**
Make sure the terminal still shows the server running. Use `http://127.0.0.1:8765/`,
not `https://` — there is no certificate, because nothing leaves your machine.

**"PNG only — detected JPEG by magic bytes"**
Your file is a JPEG, whatever its name says. The app checks the file's actual
contents, not its extension. Open it in an editor and re-save as PNG. Note that a
photo that was *ever* a JPEG has already lost its watermark permanently.

**"This file matches no protected image in the library"**
One of these is true: the file was never protected by this app; it was protected on
a different computer (the library is local); it was saved as JPEG at some point; or
it was resized or cropped. The message names the closest record it tried.

**`fetch_corpus.py` reports a hash mismatch**
A download was corrupted or a remote file changed. Delete `samples/usc_sipi` and
`samples/kodak` and run it again. This error is the check doing its job.

**Sample list is empty in the app**
You skipped Step 5. Run `python samples/fetch_corpus.py`.

**I want to start over with an empty library**
Delete `webapp/library.db`. The app recreates it on next start. Any protected file
you already downloaded becomes unverifiable — the key it needs was in that file.
