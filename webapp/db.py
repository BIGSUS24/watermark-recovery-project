"""SQLite library of protected images.

Every image this app protects is stored here byte-for-byte alongside the three
things needed to re-verify it later: the key, the image identifier bound into
every HMAC, and the (block, variant) geometry. That is what makes the
"upload a damaged copy and let the system recognise it" flow possible at all --
a fragile watermark is keyed, so without the key and the image id there is
nothing to verify against.

# ponytail: sqlite3 from the stdlib, one connection per call, no ORM, no pool.
# Ceiling: single-process local app; concurrent writers would hit SQLITE_BUSY.
# Upgrade path: WAL mode + a real pool if this ever serves more than one user.

SECURITY NOTE, stated plainly: the key is stored in the clear, in the same row
as the image. That is correct for a local single-user demonstration tool and
wrong for a deployment -- a real system keeps keys in an HSM, OS keyring, or
KMS, never beside the artefact they authenticate. The whole security argument
of this scheme rests on the attacker not having the key.
"""

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# WATERMARK_DB exists so tests can point the whole app at a throwaway file. Without
# it an integration test would write into -- and delete rows from -- the real
# library the user's own protected images live in.
DB_PATH = Path(os.environ.get("WATERMARK_DB") or Path(__file__).resolve().parent / "library.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS protected (
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
CREATE INDEX IF NOT EXISTS idx_shape ON protected (height, width, block);
CREATE INDEX IF NOT EXISTS idx_sha   ON protected (sha256);
"""

_COLS = ("id", "name", "created_at", "height", "width", "block", "variant",
         "key", "image_id", "sha256", "psnr", "ssim", "blocks")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def insert(con, *, name, height, width, block, variant, key, image_id, png,
           psnr=None, ssim=None, blocks=None) -> int:
    """Store one protected image. Returns its new row id.

    Re-protecting the same source with the same settings produces byte-identical
    output (the whole scheme is deterministic), so an exact sha256 re-hit updates
    the existing row's timestamp instead of piling up duplicates.
    """
    digest = sha256_hex(png)
    prior = con.execute("SELECT id FROM protected WHERE sha256 = ?", (digest,)).fetchone()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if prior is not None:
        con.execute("UPDATE protected SET created_at = ?, name = ? WHERE id = ?",
                    (now, name, prior["id"]))
        con.commit()
        return int(prior["id"])
    cur = con.execute(
        "INSERT INTO protected (name, created_at, height, width, block, variant, key,"
        " image_id, png, sha256, psnr, ssim, blocks)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, now, int(height), int(width), int(block), variant, key,
         sqlite3.Binary(image_id), sqlite3.Binary(png), digest,
         psnr, ssim, blocks))
    con.commit()
    return int(cur.lastrowid)


def row_meta(row) -> dict:
    """Row minus the two blobs -- safe to hand straight to jsonify."""
    out = {c: row[c] for c in _COLS}
    out["image_id"] = bytes(row["image_id"]).decode("utf-8", "replace")
    return out


def list_all(con) -> list[dict]:
    rows = con.execute("SELECT * FROM protected ORDER BY id DESC").fetchall()
    return [row_meta(r) for r in rows]


def get(con, rid: int):
    return con.execute("SELECT * FROM protected WHERE id = ?", (int(rid),)).fetchone()


def by_sha(con, digest: str):
    return con.execute("SELECT * FROM protected WHERE sha256 = ?", (digest,)).fetchone()


def candidates_for_shape(con, height: int, width: int) -> list:
    """Rows whose stored geometry could possibly match an image of this size.

    Shape is a free, exact pre-filter: a keyed verification against a row of the
    wrong dimensions is not merely wrong, it is undefined (the block grid does
    not line up), so there is no point trying one.
    """
    return con.execute(
        "SELECT * FROM protected WHERE height = ? AND width = ? ORDER BY id DESC",
        (int(height), int(width))).fetchall()


def delete(con, rid: int) -> bool:
    cur = con.execute("DELETE FROM protected WHERE id = ?", (int(rid),))
    con.commit()
    return cur.rowcount > 0


def count(con) -> int:
    return int(con.execute("SELECT COUNT(*) FROM protected").fetchone()[0])


if __name__ == "__main__":
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

    assert delete(con, rid) is True
    assert delete(con, rid) is False, "deleting a missing row must report False"
    assert count(con) == 2
    print("db.py self-check: OK")
