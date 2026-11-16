# New Fixes and Feature Log

This file records user-facing fixes and additions that are made after the
original project documentation. Add future work as a new entry using the
template at the bottom. Keep each entry factual: describe what changed, where
it changed, how a user uses it, and how it was verified.

## 2026-11-15 — Web application usability and safety updates

**Status:** Implemented and tested

### Added

1. **Image preview before protection**
   - Selected image uploads now show a preview and pixel dimensions.
   - Non-image formats such as PDF display a clear preview-unavailable message.
   - Applies to both the Protect and Verify upload areas.

2. **Operation progress indicators**
   - Protection and verification actions now show an indeterminate progress bar
     while the server is processing.
   - The indicator is also used for multi-page protection.

3. **Undo for library deletion**
   - Library deletion remains a soft delete.
   - An **Undo last delete** action restores the most recently deleted record.
   - Added `POST /api/library/<id>/restore`.
   - The underlying row is only permanently removed later by the existing purge
     operation.

4. **Library search and sorting**
   - Search protected records by filename, descriptor variant, or dimensions.
   - Sort records by newest, oldest, or name.
   - Filtering is performed in the browser after the library metadata loads.

5. **Image comparison zoom**
   - Click images in comparison and verification panels to zoom in.
   - Click again to return to the normal view.
   - This is a visual-only feature and does not affect metrics or downloaded
     files.

6. **Secret-key controls**
   - Secret keys are masked by default.
   - **Show/Hide** toggles visibility.
   - **Generate** creates a browser-side random key using
     `crypto.getRandomValues`.
   - Database key encryption still requires `WATERMARK_MASTER_KEY` when the app
     is started.

7. **Regression coverage**
   - Added `webapp/test_features.py`.
   - Tests cover library delete/restore behavior and the presence of the new
     frontend controls.

### Files changed

- `webapp/static/index.html`
- `webapp/static/app.js`
- `webapp/static/style.css`
- `webapp/server.py`
- `webapp/db.py`
- `webapp/test_features.py`

### Verification

```text
python webapp/test_features.py       2 tests passed
python webapp/db.py                  self-check passed
python src/test_e2e.py               50/50 watermark checks passed
node --check webapp/static/app.js   passed
python -m py_compile ...             passed
```

### User notes

- Refresh the browser with `Ctrl+F5` after updating the application.
- Click an image in a comparison panel to zoom.
- Use **Undo last delete** immediately after deleting a library record.
- Set `WATERMARK_MASTER_KEY` before starting the server when encrypted
  at-rest key storage is required.

---

## Future entry template

Copy this section for each future fix or feature:

```markdown
## YYYY-MM-DD — Short change title

**Status:** Planned | In progress | Implemented | Reverted

### Problem or goal

Describe the user problem, bug, or reason for the change.

### Added or changed

- Explain the behavior in user-facing terms.
- Mention important limits or compatibility notes.

### Files changed

- `path/to/file`

### Verification

```text
command or test result
```

### User notes

- Explain how to use the change, if needed.
```