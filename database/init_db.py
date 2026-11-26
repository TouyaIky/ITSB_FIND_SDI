import shutil
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

from database.demo import ensure_demo

SCHEMA_VERSION = 7


def _core_tables(sfx=""):
    """Tabel yang berubah di versi 2. `sfx` dipakai saat migrasi (tabel sementara)."""
    return f"""
CREATE TABLE users{sfx} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    nim TEXT UNIQUE,
    phone TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student','lecturer','guest','staff','security')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE found_items{sfx} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    location TEXT NOT NULL,
    date_found TEXT NOT NULL,
    time_found TEXT NOT NULL,
    photo TEXT NOT NULL,
    reporter_phone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','stored','returned')),
    received_by INTEGER REFERENCES users(id),
    received_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE lost_items{sfx} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    location TEXT NOT NULL,
    date_lost TEXT NOT NULL,
    time_lost TEXT NOT NULL,
    photo TEXT,
    reporter_phone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE item_returns{sfx} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    found_item_id INTEGER NOT NULL UNIQUE REFERENCES found_items(id),
    owner_id INTEGER REFERENCES users(id),
    owner_name TEXT NOT NULL,
    owner_type TEXT NOT NULL DEFAULT '',
    owner_phone TEXT NOT NULL DEFAULT '',
    owner_identity TEXT,
    officer_id INTEGER NOT NULL REFERENCES users(id),
    return_date TEXT NOT NULL,
    documentation_photo TEXT,
    verification_notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'returned'
);
"""


COMMON_TABLES = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    sender_name TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    category TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    email_status TEXT NOT NULL DEFAULT 'pending'
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_found_status ON found_items(status);
CREATE INDEX IF NOT EXISTS idx_found_user ON found_items(user_id);
CREATE INDEX IF NOT EXISTS idx_lost_user ON lost_items(user_id);
CREATE INDEX IF NOT EXISTS idx_lost_status ON lost_items(status);
CREATE INDEX IF NOT EXISTS idx_reset_user ON password_reset_tokens(user_id);
"""

MIGRATE_V1_V2 = """
PRAGMA foreign_keys = OFF;
BEGIN;
""" + _core_tables("_new") + """
INSERT INTO users_new(id,name,email,nim,phone,password_hash,role,created_at)
  SELECT id,name,email,nim,'',password_hash,CASE role WHEN 'admin' THEN 'security' ELSE 'student' END,created_at FROM users;
INSERT INTO found_items_new(id,user_id,item_name,category,description,location,date_found,time_found,photo,reporter_phone,status,received_by,received_at,created_at)
  SELECT id,user_id,item_name,category,description,location,date_found,time_found,photo,'',
         CASE status WHEN 'Menunggu Penyerahan' THEN 'pending' WHEN 'Tersimpan di Satpam' THEN 'stored' ELSE 'returned' END,
         received_by,received_at,created_at FROM found_items;
INSERT INTO lost_items_new(id,user_id,item_name,category,description,location,date_lost,time_lost,photo,reporter_phone,status,created_at)
  SELECT id,user_id,item_name,category,description,location,date_lost,time_lost,photo,'',
         CASE status WHEN 'Sudah Ditemukan' THEN 'resolved' ELSE 'open' END,created_at FROM lost_items;
INSERT INTO item_returns_new(id,found_item_id,owner_id,owner_name,owner_type,owner_phone,owner_identity,officer_id,return_date,documentation_photo,verification_notes,status)
  SELECT id,found_item_id,owner_id,owner_name,'','',owner_identity,officer_id,return_date,NULL,proof_notes,'returned' FROM item_returns;
DROP TABLE item_returns; DROP TABLE found_items; DROP TABLE lost_items; DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
ALTER TABLE found_items_new RENAME TO found_items;
ALTER TABLE lost_items_new RENAME TO lost_items;
ALTER TABLE item_returns_new RENAME TO item_returns;
PRAGMA user_version = 2;
COMMIT;
PRAGMA foreign_keys = ON;
"""


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def init_db(app):
    cfg = app.config
    db_path = Path(cfg["DATABASE"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    Path(cfg["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(cfg["PRIVATE_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    had_data = db_path.exists() and db_path.stat().st_size > 0
    conn = sqlite3.connect(db_path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if _has_table(conn, "users"):
        if version < 4 and had_data:                                    # cadangan sebelum mengubah skema
            conn.close()
            shutil.copy2(db_path, f"{db_path}.backup-v{version}")
            conn = sqlite3.connect(db_path)
        if version < 2:
            conn.executescript(MIGRATE_V1_V2)                           # data lama dipertahankan
    else:
        conn.executescript(_core_tables())
    conn.executescript(COMMON_TABLES + INDEXES)
    upgrade_v3(conn)                                                    # idempotent: aman dijalankan berkali-kali
    upgrade_v4(conn)
    upgrade_v5(conn)
    upgrade_v6(conn)
    upgrade_v7(conn)
    conn.commit()

    if conn.execute("SELECT COUNT(*) FROM users WHERE role='security' AND is_demo=0").fetchone()[0] == 0:
        _create_security(conn, cfg)
    ensure_demo(conn, cfg)
    conn.close()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def upgrade_v3(conn):
    """v3: penanda data demo, status tindak lanjut kritik/saran, riwayat status, tabel meta. Tidak menghapus data."""
    adds = {
        "users": [("is_demo", "INTEGER NOT NULL DEFAULT 0")],
        "found_items": [("is_demo", "INTEGER NOT NULL DEFAULT 0")],
        "lost_items": [("is_demo", "INTEGER NOT NULL DEFAULT 0")],
        "feedback": [("status", "TEXT NOT NULL DEFAULT 'new'"), ("status_reason", "TEXT"), ("internal_note", "TEXT"),
                     ("note_updated_at", "TEXT"), ("note_updated_by", "INTEGER"), ("updated_at", "TEXT"),
                     ("handled_by", "INTEGER"), ("is_demo", "INTEGER NOT NULL DEFAULT 0")],
    }
    for table, cols in adds.items():
        have = _columns(conn, table)
        for name, ddl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.executescript("""
CREATE TABLE IF NOT EXISTS feedback_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL REFERENCES feedback(id),
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by INTEGER REFERENCES users(id),
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE INDEX IF NOT EXISTS idx_fbhist_feedback ON feedback_history(feedback_id);
""")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 3:      # jangan pernah menurunkan versi skema
        conn.execute("PRAGMA user_version = 3")


def _report_table(name, kind):
    """DDL v4 untuk found_items / lost_items: status 'declined' + kolom tinjauan Satpam."""
    if kind == "found":
        specific = ("date_found TEXT NOT NULL, time_found TEXT NOT NULL, photo TEXT NOT NULL,\n"
                    "    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','stored','returned','declined')),\n"
                    "    received_by INTEGER REFERENCES users(id), received_at TEXT,")
    else:
        specific = ("date_lost TEXT NOT NULL, time_lost TEXT NOT NULL, photo TEXT,\n"
                    "    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','declined')),")
    return f"""CREATE TABLE {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    item_name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    location TEXT NOT NULL,
    {specific}
    reporter_phone TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_demo INTEGER NOT NULL DEFAULT 0,
    review_note TEXT,
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    updated_at TEXT
);
"""


_FOUND_COLS = ("id,user_id,item_name,category,description,location,date_found,time_found,photo,"
               "reporter_phone,status,received_by,received_at,created_at,is_demo")
_LOST_COLS = ("id,user_id,item_name,category,description,location,date_lost,time_lost,photo,"
              "reporter_phone,status,created_at,is_demo")


def upgrade_v4(conn):
    """v4: laporan boleh berstatus 'declined' (ditolak Satpam) + kolom review_note/reviewed_by/reviewed_at/updated_at.
    SQLite tidak bisa mengubah CHECK, jadi tabel dibangun ulang dengan menyalin seluruh data. Aman diulang."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 4:
        return
    conn.commit()
    conn.executescript(
        "PRAGMA foreign_keys = OFF;\nBEGIN;\n"
        + _report_table("found_items_new", "found") + _report_table("lost_items_new", "lost")
        + f"INSERT INTO found_items_new({_FOUND_COLS}) SELECT {_FOUND_COLS} FROM found_items;\n"
        + f"INSERT INTO lost_items_new({_LOST_COLS}) SELECT {_LOST_COLS} FROM lost_items;\n"
        + "DROP TABLE found_items; DROP TABLE lost_items;\n"
        + "ALTER TABLE found_items_new RENAME TO found_items;\nALTER TABLE lost_items_new RENAME TO lost_items;\n"
        + "CREATE INDEX IF NOT EXISTS idx_found_status ON found_items(status);\nCREATE INDEX IF NOT EXISTS idx_found_user ON found_items(user_id);\n"
        + "CREATE INDEX IF NOT EXISTS idx_lost_user ON lost_items(user_id);\nCREATE INDEX IF NOT EXISTS idx_lost_status ON lost_items(status);\n"
        + "PRAGMA user_version = 4;\nCOMMIT;\nPRAGMA foreign_keys = ON;\n")


def upgrade_v5(conn):
    """v5: tabel feedback_responses (tanggapan Satpam; banyak tanggapan per masukan, tidak pernah ditimpa). Aditif & aman diulang."""
    conn.executescript("""
CREATE TABLE IF NOT EXISTS feedback_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fbresp_feedback ON feedback_responses(feedback_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id, id);
""")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 5:
        conn.execute("PRAGMA user_version = 5")
    conn.commit()


def upgrade_v6(conn):
    """v6: notifikasi mahasiswa. `rev` naik setiap Satpam mengubah status/mengirim tanggapan; `student_seen_rev` = rev yang terakhir
    dilihat pemilik. Belum dibaca = rev > student_seen_rev. Aditif; data lama dianggap sudah dibaca (kedua kolom 0)."""
    have = _columns(conn, "feedback")
    for name in ("rev", "student_seen_rev"):
        if name not in have:
            conn.execute(f"ALTER TABLE feedback ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 6:
        conn.execute("PRAGMA user_version = 6")
    conn.commit()


def upgrade_v7(conn):
    """v7: balasan mahasiswa. `feedback_responses.from_student`=1 untuk balasan pengirim (0 = tanggapan Satpam, data lama aman).
    `feedback.srev` naik tiap pengirim membalas; `staff_seen_srev` = srev yang terakhir dilihat Satpam. Aditif."""
    if "from_student" not in _columns(conn, "feedback_responses"):
        conn.execute("ALTER TABLE feedback_responses ADD COLUMN from_student INTEGER NOT NULL DEFAULT 0")
    have = _columns(conn, "feedback")
    for name in ("srev", "staff_seen_srev"):
        if name not in have:
            conn.execute(f"ALTER TABLE feedback ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 7:
        conn.execute("PRAGMA user_version = 7")
    conn.commit()


def _create_security(conn, cfg):
    """Akun Satpam awal. Akun Satpam TIDAK bisa dibuat lewat halaman Register."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO users(name,email,nim,phone,password_hash,role) VALUES (?,?,NULL,?,?, 'security')",
        (cfg["SECURITY_NAME"], cfg["SECURITY_EMAIL"].lower(), cfg["SECURITY_PHONE"], generate_password_hash(cfg["SECURITY_PASSWORD"])))
    conn.commit()
    return cur.lastrowid
