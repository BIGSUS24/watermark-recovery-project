"""SQLite library of protected images.

Every image this app protects is stored here byte-for-byte alongside the three
things needed to re-verify it later: the key, the image identifier bound into
every HMAC, and the (block, variant) geometry. That is what makes the
"upload a damaged copy and let the system recognise it" flow possible at all --
a fragile watermark is keyed, so without the key and the image id there is
nothing to verify against.

# ponytail: sqlite3 from the stdlib, one connection per call, no ORM, no pool.
# Ceiling: single-process local app; concurrent writers would hit SQLITE_BUSY
# (WAL mode below makes readers-vs-writer contention far less likely to hit it,
# not impossible). Upgrade path: a real pool if this ever serves more than one
# user.

#16 SECURITY NOTE: the key column is encrypted at rest (AES-256-GCM, see
_encrypt_key/_decrypt_key below) under WATERMARK_MASTER_KEY. That closes the
"key sits in the clear next to the artefact it authenticates" hole -- but only
as far as the DB file goes. Whoever can read WATERMARK_MASTER_KEY (the
process's environment) can still decrypt everything; a real deployment keeps
that master key in an HSM/KMS/OS keyring, not an env var, and rotates it. The
whole security argument of this scheme rests on the attacker not having a
usable key, encrypted-at-rest or not.

#39: rows are soft-deleted (deleted_at set, never DELETE'd) so a mistaken
delete is recoverable and an export taken right before a delete still means
something. purge() is the explicit, separate, irreversible step.
"""

import base64
import binascii
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# WATERMARK_DB exists so tests can point the whole app at a throwaway file. Without
# it an integration test would write into -- and delete rows from -- the real
# library the user's own protected images live in.
DB_PATH = Path(os.environ.get("WATERMARK_DB") or Path(__file__).resolve().parent / "library.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS protected (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    deleted_at  TEXT,
    height      INTEGER NOT NULL,
    width       INTEGER NOT NULL,
    block       INTEGER NOT NULL,
    variant     TEXT    NOT NULL,
    key         BLOB    NOT NULL,
    key_encrypted INTEGER NOT NULL DEFAULT 0,
    image_id    BLOB    NOT NULL,
    png         BLOB    NOT NULL,
    sha256      TEXT    NOT NULL,
    psnr        REAL,
    ssim        REAL,
    blocks      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_shape ON protected (height, width, block);
CREATE INDEX IF NOT EXISTS idx_sha   ON protected (sha256);
"""

# Columns added to the schema after the table first shipped. CREATE TABLE IF NOT
# EXISTS above only helps a brand-new DB file; an existing library.db from before
# #16/#39 needs these back-filled by ALTER TABLE, on every connect() (idempotent --
# skipped once the column already exists). Note this does NOT change the stored
# TYPE of pre-existing columns (SQLite can't cheaply do that) -- `key` on a
# pre-#16 row is still physically TEXT storage class, which is exactly what
# _as_bytes() below exists to paper over.
_LEGACY_COLUMNS = {
    "deleted_at": "ALTER TABLE protected ADD COLUMN deleted_at TEXT",
    "key_encrypted": "ALTER TABLE protected ADD COLUMN key_encrypted INTEGER NOT NULL DEFAULT 0",
}

# Row -> JSON metadata never includes "key": before #16 it was plaintext and would
# have leaked the secret straight into every /api/library and /api/verify response;
# now it is an encrypted blob (raw bytes), which jsonify can't even serialize. Callers
# that need the usable key call decrypt_key() explicitly, never row_meta().
_COLS = ("id", "name", "created_at", "deleted_at", "height", "width", "block", "variant",
         "key_encrypted", "image_id", "sha256", "psnr", "ssim", "blocks")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")  # #39 -- silently no-ops on :memory:
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(protected)")}
    for col, ddl in _LEGACY_COLUMNS.items():
        if col not in cols:
            con.execute(ddl)
    con.commit()
    return con


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_bytes(v) -> bytes:
    """SQLite is dynamically typed by column VALUE, not just declared column type:
    a `key` row written back when the column was TEXT (any pre-#16 library.db)
    still comes back from sqlite3 as `str`, never `bytes`, even after connect()'s
    ALTER TABLE back-fills the newer columns. `bytes(a_str)` raises TypeError --
    it needs `.encode()`, not a cast -- so every reader of row["key"] must go
    through this one coercion instead of guessing at each call site."""
    return v if isinstance(v, bytes) else v.encode("utf-8")


# ---------------------------------------------------------------------------
# #16: key encryption at rest -- AES-256-GCM, one random 12-byte nonce per row,
# stored as nonce || ciphertext||tag (AESGCM.encrypt() appends the tag itself,
# which is the whole point of using an AEAD instead of inventing a construction).
#
# The row's own id is bound in as associated data (authenticated, not encrypted):
# without it, someone with write access to the DB file but no master key could
# swap two rows' ciphertexts and both would still decrypt "successfully", just
# under the wrong row -- AAD makes that swap fail decryption instead of
# succeeding silently. This does mean insert() has to know its own new row id
# before it can encrypt, which is why it writes a placeholder first (see below).
# ---------------------------------------------------------------------------

_NONCE_LEN = 12
# Fixed, not random-per-install: HKDF needs a salt to turn a low-entropy passphrase
# into a key, but that salt has to be reproducible on every process start with no
# extra place to store it. ponytail: this means two installs using the same weak
# passphrase derive the same key (no per-install salt). Ceiling: fine as long as
# WATERMARK_MASTER_KEY is either a real 32-byte key or a passphrase nobody else
# could plausibly guess. Upgrade path: persist a random salt next to the DB file
# and pass it in here instead, if that ceiling is ever a real threat model.
_HKDF_SALT = b"watermark-recovery-project/webapp/db.py#16"


def _parse_master_key_value(raw: str) -> bytes:
    """hex (64 chars -> 32 bytes) or base64 (32 bytes) is used as-is; anything else
    is treated as a passphrase and stretched to 32 bytes with HKDF-SHA256, per the
    #16 spec ("derive with HKDF-SHA256 if it's a passphrase").

    Ambiguity, named rather than hidden: a passphrase that happens to be valid
    base64 AND happens to decode to exactly 32 bytes is indistinguishable from a
    deliberately-supplied raw key, and is silently accepted as one instead of
    being stretched. Vanishingly unlikely for a human-chosen passphrase (32 raw
    bytes of base64 alphabet, decoding cleanly) and not worth a format flag for.
    """
    try:
        b = bytes.fromhex(raw)
        if len(b) == 32:
            return b
    except ValueError:
        pass
    try:
        b = base64.b64decode(raw, validate=True)
        if len(b) == 32:
            return b
    except (binascii.Error, ValueError):
        pass
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT,
                info=b"WATERMARK_MASTER_KEY")
    return hkdf.derive(raw.encode("utf-8"))


def _load_master_key() -> bytes | None:
    raw = os.environ.get("WATERMARK_MASTER_KEY")
    return _parse_master_key_value(raw) if raw else None


def parse_master_key(raw: str) -> bytes:
    """Public wrapper for callers (webapp/server.py's /api/export) that supply a
    master key from the request instead of -- or as well as -- the environment.
    Same hex/base64/passphrase rules as WATERMARK_MASTER_KEY."""
    return _parse_master_key_value(raw)


def _encrypt_key(plain_key: str, master: bytes, row_id: int) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    aad = str(int(row_id)).encode("ascii")
    ct = AESGCM(master).encrypt(nonce, plain_key.encode("utf-8"), aad)
    return nonce + ct


def _decrypt_key(blob: bytes, master: bytes, row_id: int) -> str:
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    aad = str(int(row_id)).encode("ascii")
    return AESGCM(master).decrypt(nonce, ct, aad).decode("utf-8")


def decrypt_key(row, master: bytes | None = None) -> str:
    """The row's key, in the clear, for handing to embed/detect/identify. Every
    caller in server.py wants this, not the raw column -- which is the whole point
    of keeping "key" out of row_meta()."""
    blob = _as_bytes(row["key"])
    if not row["key_encrypted"]:
        return blob.decode("utf-8")
    if master is None:
        master = _load_master_key()
    if master is None:
        raise RuntimeError(
            "this row's key is encrypted but WATERMARK_MASTER_KEY is not set -- "
            "cannot verify or repair anything against it")
    return _decrypt_key(blob, master, row["id"])


class PlaintextKeysError(RuntimeError):
    """Raised by check_plaintext_keys() -- see its docstring."""


def _con_path(con) -> str:
    """Best-effort actual file path of an open connection, for log/error messages.
    `con` is not always DB_PATH -- the self-check uses :memory: and tempfiles,
    WATERMARK_DB points tests elsewhere -- so hardcoding the module-level DB_PATH
    constant into a message about `con` was misleading about which file it meant."""
    try:
        row = con.execute("PRAGMA database_list").fetchone()
        return row["file"] or ":memory:"
    except Exception:
        return str(DB_PATH)


def check_plaintext_keys(con, allow_plaintext: bool = False) -> None:
    """#16's startup gate. webapp/server.py calls this once, right after its first
    connect(), before app.run(). Three outcomes:

      - No plaintext rows: nothing to do.
      - Plaintext rows exist AND a master key is configured: encrypt them right
        now (via migrate_encrypt()) and log how many rows were converted. Setting
        WATERMARK_MASTER_KEY is what an operator does to fix this; making them
        also remember a separate --migrate-encrypt step is one avoidable footgun
        away from "the env var is set and the secrets are still in the clear
        forever" -- so the gate itself closes the gap instead of just noticing it.
      - Plaintext rows exist and no master key: refuse to start, unless the
        caller passed --allow-plaintext-keys (server.py's CLI flag).
    """
    n = con.execute("SELECT COUNT(*) FROM protected WHERE key_encrypted = 0").fetchone()[0]
    if not n:
        return
    where = _con_path(con)  # NOT DB_PATH -- con may be :memory:/tempfile/WATERMARK_DB
    master = _load_master_key()
    if master is not None:
        migrated = migrate_encrypt(con, master)
        print(f"check_plaintext_keys: WATERMARK_MASTER_KEY is set -- encrypted "
              f"{migrated} previously-plaintext row(s) in {where}.")
        return
    if allow_plaintext:
        return
    raise PlaintextKeysError(
        f"{n} row(s) in {where} still store their key in plaintext, and "
        "WATERMARK_MASTER_KEY is not set, so this app has no way to encrypt "
        "them. Set WATERMARK_MASTER_KEY (a 32-byte key, hex or base64, or a "
        "passphrase) and restart -- plaintext rows are encrypted automatically "
        "the moment a master key is available -- or start with "
        "--allow-plaintext-keys to accept the risk and continue as-is.")


def migrate_encrypt(con, master: bytes) -> int:
    """One-shot migration for an existing library.db: encrypt every row whose key
    is still plaintext, in place. Includes soft-deleted rows -- a deleted row's key
    is still a live secret sitting in the file until purge() actually removes it.

    Works against a genuine pre-#16 database too (key column still physically
    TEXT storage, no key_encrypted/deleted_at until connect()'s ALTER TABLE ran)
    -- that is the whole point of _as_bytes() below, see its docstring.
    """
    rows = con.execute("SELECT id, key FROM protected WHERE key_encrypted = 0").fetchall()
    for row in rows:
        plain = _as_bytes(row["key"]).decode("utf-8")
        blob = _encrypt_key(plain, master, row["id"])
        con.execute("UPDATE protected SET key = ?, key_encrypted = 1 WHERE id = ?",
                    (sqlite3.Binary(blob), row["id"]))
    con.commit()
    return len(rows)


def _prepare_key(key: str, row_id: int, master: bytes | None) -> tuple[bytes, int]:
    """key -> (stored blob, key_encrypted flag). Split out of insert() because it
    needs the row's own id for AAD (see the AEAD note above), so insert() calls
    this only after the row already exists."""
    if master is not None:
        return _encrypt_key(key, master, row_id), 1
    return key.encode("utf-8"), 0


def insert(con, *, name, height, width, block, variant, key, image_id, png,
           psnr=None, ssim=None, blocks=None) -> int:
    """Store one protected image. Returns its new row id.

    Re-protecting the same source with the same settings produces byte-identical
    output (the whole scheme is deterministic), so an exact sha256 re-hit updates
    the existing row's timestamp instead of piling up duplicates. Soft-deleted rows
    are not candidates for that dedup -- re-protecting after a delete makes a fresh
    row, it does not resurrect the old one.

    `key` is the plaintext secret. Encrypting it needs the row's own id as AAD
    (see the AEAD note above), which SQLite only hands out once the row exists --
    so a genuinely new row is written once with a placeholder key, then updated
    with the real (possibly-encrypted) one, all inside one transaction/commit; a
    deduped re-protect never reaches this path at all.
    """
    digest = sha256_hex(png)
    prior = con.execute(
        "SELECT id FROM protected WHERE sha256 = ? AND deleted_at IS NULL",
        (digest,)).fetchone()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if prior is not None:
        con.execute("UPDATE protected SET created_at = ?, name = ? WHERE id = ?",
                    (now, name, prior["id"]))
        con.commit()
        return int(prior["id"])

    cur = con.execute(
        "INSERT INTO protected (name, created_at, height, width, block, variant, key,"
        " key_encrypted, image_id, png, sha256, psnr, ssim, blocks)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, now, int(height), int(width), int(block), variant,
         sqlite3.Binary(b""), 0,  # placeholder -- replaced below once the id exists
         sqlite3.Binary(image_id), sqlite3.Binary(png), digest,
         psnr, ssim, blocks))
    new_id = int(cur.lastrowid)  # available immediately after execute(), pre-commit

    key_blob, key_encrypted = _prepare_key(key, new_id, _load_master_key())
    con.execute("UPDATE protected SET key = ?, key_encrypted = ? WHERE id = ?",
                (sqlite3.Binary(key_blob), key_encrypted, new_id))
    con.commit()
    return new_id


def row_meta(row) -> dict:
    """Row minus the blobs (png, key) -- safe to hand straight to jsonify."""
    out = {c: row[c] for c in _COLS}
    out["image_id"] = bytes(row["image_id"]).decode("utf-8", "replace")
    out["key_encrypted"] = bool(out["key_encrypted"])
    return out


def list_all(con) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM protected WHERE deleted_at IS NULL ORDER BY id DESC").fetchall()
    return [row_meta(r) for r in rows]


def list_all_rows(con) -> list:
    """Full rows (including the png/key blobs), non-deleted -- for callers that
    need the actual bytes, like /api/export. list_all() strips blobs for the JSON
    API; row_meta() still keeps "key" off of either."""
    return con.execute(
        "SELECT * FROM protected WHERE deleted_at IS NULL ORDER BY id DESC").fetchall()


def get(con, rid: int):
    return con.execute(
        "SELECT * FROM protected WHERE id = ? AND deleted_at IS NULL", (int(rid),)).fetchone()


def by_sha(con, digest: str):
    return con.execute(
        "SELECT * FROM protected WHERE sha256 = ? AND deleted_at IS NULL", (digest,)).fetchone()


def candidates_for_shape(con, height: int, width: int) -> list:
    """Rows whose stored geometry could possibly match an image of this size.

    Shape is a free, exact pre-filter: a keyed verification against a row of the
    wrong dimensions is not merely wrong, it is undefined (the block grid does
    not line up), so there is no point trying one.
    """
    return con.execute(
        "SELECT * FROM protected WHERE height = ? AND width = ? AND deleted_at IS NULL"
        " ORDER BY id DESC",
        (int(height), int(width))).fetchall()


def delete(con, rid: int) -> bool:
    """#39: soft delete. Sets deleted_at instead of removing the row, so every read
    path above (list_all/get/by_sha/candidates_for_shape/count) stops seeing it
    immediately, but the bytes are still on disk until purge() runs."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = con.execute(
        "UPDATE protected SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (now, int(rid)))
    con.commit()
    return cur.rowcount > 0


def purge(con, older_than_days: int = 30) -> int:
    """Hard-delete rows soft-deleted more than `older_than_days` days ago. This is
    the only irreversible step in the soft-delete story -- delete() never is."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat(
        timespec="seconds")
    cur = con.execute(
        "DELETE FROM protected WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))
    con.commit()
    return cur.rowcount


def count(con) -> int:
    return int(con.execute(
        "SELECT COUNT(*) FROM protected WHERE deleted_at IS NULL").fetchone()[0])


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="webapp/db.py -- protected-image library")
    ap.add_argument("--migrate-encrypt", action="store_true",
                     help="One-shot: encrypt every plaintext-key row in the real "
                          "library.db (or $WATERMARK_DB) using WATERMARK_MASTER_KEY, "
                          "then exit. Run with no flags for the module self-check.")
    args = ap.parse_args()

    if args.migrate_encrypt:
        master = _load_master_key()
        if master is None:
            raise SystemExit("WATERMARK_MASTER_KEY is not set -- nothing to encrypt with.")
        real_con = connect()
        try:
            n = migrate_encrypt(real_con, master)
            print(f"migrate-encrypt: encrypted {n} row(s) in {DB_PATH}")
        finally:
            real_con.close()
        raise SystemExit(0)

    # Self-check: in-memory DB, so it can never touch the real library.
    con = connect(":memory:")
    assert count(con) == 0

    png_a = b"\x89PNG\r\n\x1a\n" + b"aaa"
    png_b = b"\x89PNG\r\n\x1a\n" + b"bbb"
    rid = insert(con, name="a.png", height=64, width=64, block=8, variant="A",
                 key="k", image_id=b"a|64x64|8", png=png_a, psnr=43.1, ssim=0.98, blocks=64)
    assert count(con) == 1

    # Determinism dedup: same bytes must reuse the row, not create a second one.
    again = insert(con, name="a-again.png", height=64, width=64, block=8, variant="A",
                   key="k", image_id=b"a|64x64|8", png=png_a)
    assert again == rid, (again, rid)
    assert count(con) == 1, "identical PNG must not create a duplicate row"
    assert get(con, rid)["name"] == "a-again.png", "dedup should refresh the name"

    rid_b = insert(con, name="b.png", height=64, width=64, block=8, variant="B",
                   key="k2", image_id=b"b|64x64|8", png=png_b)
    assert rid_b != rid and count(con) == 2

    # Different bytes at a different size must NOT be offered as a shape candidate.
    insert(con, name="c.png", height=32, width=32, block=8, variant="A",
           key="k", image_id=b"c|32x32|8", png=png_b + b"c")
    assert len(candidates_for_shape(con, 64, 64)) == 2
    assert len(candidates_for_shape(con, 32, 32)) == 1
    assert candidates_for_shape(con, 99, 99) == []

    # Blobs must survive the round trip byte-exactly, and metadata must not leak them.
    assert bytes(get(con, rid)["png"]) == png_a
    assert bytes(get(con, rid)["image_id"]) == b"a|64x64|8"
    assert by_sha(con, sha256_hex(png_b))["id"] == rid_b
    meta = list_all(con)[0]
    assert "png" not in meta and isinstance(meta["image_id"], str)
    assert "key" not in meta, "#16: the key -- encrypted or not -- must never reach JSON"

    assert delete(con, rid) is True
    assert delete(con, rid) is False, "deleting a missing row must report False"
    assert count(con) == 2

    # --- #39: soft delete is really soft, and purge() is the irreversible step ---
    rid_sd = insert(con, name="softdel.png", height=16, width=16, block=8, variant="A",
                     key="k", image_id=b"sd|16x16|8", png=b"\x89PNGsoftdel")
    before = count(con)
    assert delete(con, rid_sd) is True
    assert count(con) == before - 1
    assert get(con, rid_sd) is None, "a soft-deleted row must not be readable via get()"
    assert by_sha(con, sha256_hex(b"\x89PNGsoftdel")) is None
    assert all(r["id"] != rid_sd for r in list_all(con))
    assert all(r["id"] != rid_sd for r in candidates_for_shape(con, 16, 16))
    raw = con.execute("SELECT deleted_at FROM protected WHERE id = ?", (rid_sd,)).fetchone()
    assert raw["deleted_at"] is not None, "the row must still physically exist, just marked"

    # purge() only removes rows soft-deleted further back than the cutoff.
    assert purge(con, older_than_days=30) == 0, "a row deleted seconds ago is not yet due"
    con.execute("UPDATE protected SET deleted_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", rid_sd))
    con.commit()
    assert purge(con, older_than_days=30) == 1
    assert con.execute("SELECT * FROM protected WHERE id = ?", (rid_sd,)).fetchone() is None, (
        "purge() must hard-delete rows past the cutoff")

    # --- WAL mode: only meaningfully testable against a real file (:memory: can't
    # use WAL and silently stays on its default journal mode instead). ---
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        wal_con = connect(Path(td) / "wal_check.db")
        mode = wal_con.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", mode
        wal_con.close()

    # --- #16: key encryption at rest -------------------------------------------
    _saved_master_env = os.environ.pop("WATERMARK_MASTER_KEY", None)
    try:
        # No master key configured: the original local-demo behaviour (keys stored,
        # and read back, in the clear) is preserved as an explicit, un-hidden choice.
        rid_plain = insert(con, name="plain.png", height=16, width=16, block=8,
                            variant="A", key="plaintext-secret", image_id=b"p|16x16|8",
                            png=b"\x89PNGplain")
        row = get(con, rid_plain)
        assert row["key_encrypted"] == 0
        assert decrypt_key(row) == "plaintext-secret"

        # A DB with a plaintext row and no master key must refuse to start...
        try:
            check_plaintext_keys(con)
            raise AssertionError("must refuse against a plaintext-key DB with no master key")
        except PlaintextKeysError:
            pass
        # ...unless the caller explicitly opts out, in which case NOTHING gets
        # touched -- allow_plaintext means "let me run like this", not "encrypt it".
        check_plaintext_keys(con, allow_plaintext=True)
        assert get(con, rid_plain)["key_encrypted"] == 0

        # With a master key set, new rows are encrypted directly by insert(), bound
        # to their own row id, and decrypt_key() round-trips exactly.
        os.environ["WATERMARK_MASTER_KEY"] = os.urandom(32).hex()
        rid_enc = insert(con, name="enc.png", height=16, width=16, block=8,
                          variant="A", key="super-secret-key", image_id=b"e|16x16|8",
                          png=b"\x89PNGenc")
        row_e = get(con, rid_enc)
        assert row_e["key_encrypted"] == 1
        assert bytes(row_e["key"]) != b"super-secret-key", "must not be stored in the clear"
        assert decrypt_key(row_e) == "super-secret-key"
        # AAD is bound to the row id: decrypting row_e's ciphertext as if it were
        # some other row's must fail rather than quietly succeed.
        wrong_id_decrypted = True
        try:
            _decrypt_key(bytes(row_e["key"]), _load_master_key(), row_e["id"] + 1)
        except Exception:
            wrong_id_decrypted = False
        assert not wrong_id_decrypted, "decrypting under the wrong row id must fail"

        # Defect 2 regression: the startup gate must not just wave plaintext rows
        # through once a master key exists -- it must encrypt them right then.
        assert get(con, rid_plain)["key_encrypted"] == 0, "sanity: still plaintext pre-gate"
        check_plaintext_keys(con)
        assert get(con, rid_plain)["key_encrypted"] == 1, "the gate must migrate in place"
        assert decrypt_key(get(con, rid_plain)) == "plaintext-secret"

        # A passphrase-form master key derives deterministically (same input -> same
        # 32-byte key every time, which is required -- it has to survive a restart).
        os.environ["WATERMARK_MASTER_KEY"] = "a plain-English passphrase, not hex or base64"
        k1 = _load_master_key()
        k2 = _load_master_key()
        assert k1 == k2 and len(k1) == 32
        assert parse_master_key(os.environ["WATERMARK_MASTER_KEY"]) == k1

        # migrate_encrypt() directly: nothing left to do, since the gate above
        # already converted every plaintext row (idempotency, not a no-op bug).
        assert migrate_encrypt(con, k1) == 0

        # --- Defect 1 regression: a genuine pre-#16 library.db (key column still
        # physically TEXT, no deleted_at, no key_encrypted) must not crash either
        # decrypt_key() or migrate_encrypt() -- that was the whole bug: a real
        # existing library had no path forward at all. ---
        with tempfile.TemporaryDirectory() as td:
            legacy_path = Path(td) / "legacy.db"
            legacy_raw = sqlite3.connect(str(legacy_path))
            legacy_raw.executescript("""
                CREATE TABLE protected (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL,
                    height      INTEGER NOT NULL,
                    width       INTEGER NOT NULL,
                    block       INTEGER NOT NULL,
                    variant     TEXT    NOT NULL,
                    key         TEXT    NOT NULL,
                    image_id    BLOB    NOT NULL,
                    png         BLOB    NOT NULL,
                    sha256      TEXT    NOT NULL,
                    psnr        REAL,
                    ssim        REAL,
                    blocks      INTEGER
                );
            """)
            legacy_raw.execute(
                "INSERT INTO protected (name, created_at, height, width, block, variant,"
                " key, image_id, png, sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("legacy.png", "2020-01-01T00:00:00+00:00", 16, 16, 8, "A",
                 "legacy-plaintext-key", sqlite3.Binary(b"legacy-id"),
                 sqlite3.Binary(b"\x89PNGlegacy"), sha256_hex(b"\x89PNGlegacy")))
            legacy_raw.commit()
            legacy_raw.close()

            legacy_con = connect(legacy_path)  # runs the ALTER TABLE back-fill
            legacy_row = legacy_con.execute("SELECT * FROM protected").fetchone()
            assert isinstance(legacy_row["key"], str), (
                "reproduction depends on the pre-#16 TEXT-storage shape")
            assert decrypt_key(legacy_row) == "legacy-plaintext-key"

            legacy_master = os.urandom(32)
            n_legacy = migrate_encrypt(legacy_con, legacy_master)
            assert n_legacy == 1
            legacy_row = legacy_con.execute(
                "SELECT * FROM protected WHERE id = ?", (legacy_row["id"],)).fetchone()
            assert legacy_row["key_encrypted"] == 1
            assert decrypt_key(legacy_row, legacy_master) == "legacy-plaintext-key"
            legacy_con.close()
    finally:
        if _saved_master_env is None:
            os.environ.pop("WATERMARK_MASTER_KEY", None)
        else:
            os.environ["WATERMARK_MASTER_KEY"] = _saved_master_env

    print("db.py self-check: OK (soft-delete, purge, WAL, encryption, legacy-DB migration)")
