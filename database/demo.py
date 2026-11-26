"""Akun demonstrasi (Demo Mahasiswa dan Demo Satpam) dan pembersihan data demo.

Aturan:
- Hanya dua akun demo. Dibuat sekali (idempotent): restart tidak menggandakan apa pun.
- TIDAK ADA data contoh. Akun demo dimulai bersih: tanpa barang, laporan, riwayat, atau kritik/saran palsu.
- Semua aktivitas yang dibuat lewat akun demo ditandai is_demo=1, sehingga terpisah dari data asli
  dan dapat dihapus kapan saja (`python manage.py reset-demo --yes`) tanpa menyentuh data asli.
- Akun yang sudah ada dan bukan akun demo TIDAK PERNAH diubah.
- Basis data lama yang pernah diisi data contoh versi sebelumnya dibersihkan SATU KALI secara otomatis
  (hanya baris is_demo=1; akun, data asli, dan struktur tabel tidak disentuh).
"""
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

log = logging.getLogger(__name__)
LEGACY_SEED_KEY = "demo_data_v1"          # penanda seeder lama (sudah dihapus)
PURGED_KEY = "demo_data_purged_v4"


def _meta_get(conn, key):
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def _ensure_account(conn, email, name, nim, phone, password, role):
    row = conn.execute("SELECT id,is_demo,role,password_hash FROM users WHERE email=?", (email,)).fetchone()
    if row is None:
        try:
            cur = conn.execute("INSERT INTO users(name,email,nim,phone,password_hash,role,is_demo) VALUES (?,?,?,?,?,?,1)",
                               (name, email, nim, phone, generate_password_hash(password), role))
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            log.warning("Akun demo %s tidak dibuat (NIM/email bentrok).", email)
            return None
    if not row[1] or row[2] != role:       # akun asli dengan email yang sama: jangan disentuh
        log.warning("Email demo %s sudah dipakai akun lain; akun demo dilewati.", email)
        return None
    conn.execute("UPDATE users SET name=? WHERE id=? AND name!=?", (name, row[0], name))   # nama tampilan demo selalu seragam
    if not check_password_hash(row[3], password):      # sinkronkan jika password demo diubah lewat .env
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), row[0]))
        conn.commit()
    return row[0]


def ensure_demo(conn, cfg):
    """Pastikan dua akun demo ada. Tidak membuat data apa pun selain akun."""
    if not cfg["DEMO_ENABLED"]:
        return
    _ensure_account(conn, cfg["DEMO_USER_EMAIL"], "Demo Mahasiswa", "DEMO0001", "081200000101", cfg["DEMO_USER_PASSWORD"], "student")
    _ensure_account(conn, cfg["DEMO_SECURITY_EMAIL"], "Demo Satpam", None, "081200000102", cfg["DEMO_SECURITY_PASSWORD"], "security")
    if _meta_get(conn, LEGACY_SEED_KEY) is not None and _meta_get(conn, PURGED_KEY) is None:
        purge_demo_activity(conn, cfg["UPLOAD_FOLDER"], cfg["PRIVATE_UPLOAD_FOLDER"])
        log.info("Data contoh demo versi lama dibersihkan.")
    if _meta_get(conn, PURGED_KEY) is None:
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)", (PURGED_KEY, datetime.now().isoformat(timespec="seconds")))
        conn.commit()


def _unlink(folder, names):
    for n in names:
        if n:
            (Path(folder) / Path(str(n)).name).unlink(missing_ok=True)


def purge_demo_activity(conn, upload, private):
    """Hapus SEMUA aktivitas akun demo (barang, laporan, pengembalian, kritik/saran, riwayat) tetapi pertahankan
    kedua akun demo. Data asli tidak disentuh. Foto yang terkait ikut dihapus."""
    q = conn.execute
    photos = [r[0] for r in q("SELECT photo FROM found_items WHERE is_demo=1")] + \
             [r[0] for r in q("SELECT photo FROM lost_items WHERE is_demo=1")]
    docs = [r[0] for r in q("SELECT documentation_photo FROM item_returns WHERE found_item_id IN (SELECT id FROM found_items WHERE is_demo=1)")]
    q("DELETE FROM item_returns WHERE found_item_id IN (SELECT id FROM found_items WHERE is_demo=1)")
    q("DELETE FROM feedback_responses WHERE feedback_id IN (SELECT id FROM feedback WHERE is_demo=1)")
    q("DELETE FROM feedback_history WHERE feedback_id IN (SELECT id FROM feedback WHERE is_demo=1)")
    q("DELETE FROM feedback WHERE is_demo=1")
    q("DELETE FROM found_items WHERE is_demo=1")
    q("DELETE FROM lost_items WHERE is_demo=1")
    conn.commit()
    _unlink(upload, photos)
    _unlink(private, docs)
    for folder in (upload, private):            # sisa berkas seeder lama
        for f in Path(folder).glob("demo_*"):
            f.unlink(missing_ok=True)


def remove_demo(conn, upload, private):
    """Hapus akun demo BESERTA seluruh aktivitasnya (data asli aman)."""
    purge_demo_activity(conn, upload, private)
    conn.execute("DELETE FROM password_reset_tokens WHERE user_id IN (SELECT id FROM users WHERE is_demo=1)")
    conn.execute("DELETE FROM users WHERE is_demo=1")
    conn.execute("DELETE FROM meta WHERE key IN (?,?)", (LEGACY_SEED_KEY, PURGED_KEY))
    conn.commit()
