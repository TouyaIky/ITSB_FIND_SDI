"""Kritik & saran + tindak lanjut Satpam. Status: new | reviewing | in_progress | done | rejected."""
from config.settings import FEEDBACK_STATUSES
from database.db import execute, get_db, query

STATUS_CODES = [c for c, _, _ in FEEDBACK_STATUSES]
PER_PAGE = 10


def create(user_id, name, email, category, subject, message, is_demo=0):
    db = get_db()
    cur = db.execute("INSERT INTO feedback(user_id,sender_name,sender_email,category,subject,message,is_demo) VALUES (?,?,?,?,?,?,?)",
                     (user_id, name, email, category, subject, message, is_demo))
    db.execute("INSERT INTO feedback_history(feedback_id,old_status,new_status,changed_by) VALUES (?,NULL,'new',NULL)", (cur.lastrowid,))
    db.commit()
    return cur.lastrowid


def recent_duplicate(email, message):
    return query("SELECT 1 FROM feedback WHERE sender_email=? AND message=? AND created_at >= datetime('now','-2 minutes')",
                 (email, message), one=True) is not None


def get(fid, demo_only=False):
    return query("SELECT f.*, h.name AS handler, n.name AS note_author FROM feedback f LEFT JOIN users h ON h.id=f.handled_by "
                 "LEFT JOIN users n ON n.id=f.note_updated_by WHERE f.id=?" + (" AND f.is_demo=1" if demo_only else ""), (fid,), one=True)


def history(fid):
    return query("SELECT h.*, u.name AS actor FROM feedback_history h LEFT JOIN users u ON u.id=h.changed_by "
                 "WHERE h.feedback_id=? ORDER BY h.id DESC", (fid,))


def stats(demo_only=False):
    rows = query("SELECT status, COUNT(*) n FROM feedback" + (" WHERE is_demo=1" if demo_only else "") + " GROUP BY status")
    out = {c: 0 for c in STATUS_CODES}
    for r in rows:
        out[r["status"]] = r["n"]
    out["total"] = sum(out.values())
    return out


def search(q="", status="", category="", sort="newest", page=1, demo_only=False, resp=""):
    where, args = ["1=1"], []
    if demo_only:
        where.append("f.is_demo=1")
    if status in STATUS_CODES:
        where.append("f.status=?"); args.append(status)
    if category:
        where.append("f.category=?"); args.append(category)
    if resp == "none":
        where.append("NOT EXISTS (SELECT 1 FROM feedback_responses r WHERE r.feedback_id=f.id AND r.from_student=0)")
    elif resp == "yes":
        where.append("EXISTS (SELECT 1 FROM feedback_responses r WHERE r.feedback_id=f.id AND r.from_student=0)")
    elif resp == "reply":                      # ada balasan baru dari pengirim yang belum dibuka Satpam
        where.append("f.srev>f.staff_seen_srev")
    if q:
        where.append("(f.sender_name LIKE ? OR f.subject LIKE ? OR f.message LIKE ?)"); args += [f"%{q}%"] * 3
    w = " AND ".join(where)
    total = query(f"SELECT COUNT(*) n FROM feedback f WHERE {w}", args, one=True)["n"]
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, page), pages)
    order = "f.id ASC" if sort == "oldest" else "f.id DESC"
    rows = query("SELECT f.*, (SELECT COUNT(*) FROM feedback_responses r WHERE r.feedback_id=f.id AND r.from_student=0) AS n_resp, (f.srev>f.staff_seen_srev) AS reply_unread, "
                 f"CAST(julianday('now') - julianday(f.created_at) AS INTEGER) AS age_days FROM feedback f WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?", args + [PER_PAGE, (page - 1) * PER_PAGE])
    return rows, total, page, pages


def unanswered(demo_only=False):
    """Jumlah masukan yang belum pernah ditanggapi Satpam."""
    return query("SELECT COUNT(*) n FROM feedback f WHERE NOT EXISTS (SELECT 1 FROM feedback_responses r WHERE r.feedback_id=f.id AND r.from_student=0)"
                 + (" AND f.is_demo=1" if demo_only else ""), one=True)["n"]


def change_status(fid, new_status, officer_id, reason=""):
    """Ubah status + catat riwayat dalam satu transaksi. Return False jika status tidak berubah/tidak valid."""
    if new_status not in STATUS_CODES:
        return False
    db = get_db()
    row = db.execute("SELECT status FROM feedback WHERE id=?", (fid,)).fetchone()
    if row is None or row["status"] == new_status:
        return False
    try:
        db.execute("UPDATE feedback SET status=?, status_reason=?, updated_at=datetime('now','localtime'), handled_by=?, rev=rev+1 WHERE id=?",
                   (new_status, reason or None if new_status == "rejected" else None, officer_id, fid))
        db.execute("INSERT INTO feedback_history(feedback_id,old_status,new_status,changed_by,note,created_at) VALUES (?,?,?,?,?,datetime('now','localtime'))",
                   (fid, row["status"], new_status, officer_id, reason or None))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def set_note(fid, note, officer_id):
    execute("UPDATE feedback SET internal_note=?, note_updated_at=datetime('now','localtime'), note_updated_by=? WHERE id=?",
            (note or None, officer_id, fid))


def add_response(fid, officer_id, message):
    """Tambah tanggapan Satpam. Selalu INSERT baru: tanggapan sebelumnya tidak pernah tertimpa."""
    db = get_db()
    cur = db.execute("INSERT INTO feedback_responses(feedback_id,message,created_by) VALUES (?,?,?)", (fid, message, officer_id))
    db.execute("UPDATE feedback SET updated_at=datetime('now','localtime'), handled_by=?, rev=rev+1 WHERE id=?", (officer_id, fid))
    db.commit()
    return cur.lastrowid


def responses(fid):
    """Semua tanggapan (terlama dulu) beserta nama petugas."""
    return query("SELECT r.id, r.message, r.created_at, r.from_student, u.name AS officer FROM feedback_responses r "
                 "LEFT JOIN users u ON u.id=r.created_by WHERE r.feedback_id=? ORDER BY r.id ASC", (fid,))


# ---- sisi mahasiswa: SELALU dibatasi user_id; kolom internal (internal_note dst.) tidak pernah dipilih ----
MINE_COLS = "f.id,f.category,f.subject,f.message,f.created_at,f.status,f.status_reason,f.updated_at,(SELECT COUNT(*) FROM feedback_responses r WHERE r.feedback_id=f.id AND r.from_student=0) AS n_resp,(f.rev>f.student_seen_rev) AS unread"


def latest_by_user(uid, limit=5):
    """Dashboard: hanya `limit` terbaru milik uid (LIMIT di SQL, bukan disembunyikan di frontend)."""
    return query(f"SELECT {MINE_COLS} FROM feedback f WHERE f.user_id=? ORDER BY f.id DESC LIMIT ?", (uid, limit))


def page_by_user(uid, page=1, per_page=10):
    total = query("SELECT COUNT(*) n FROM feedback WHERE user_id=?", (uid,), one=True)["n"]
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = query(f"SELECT {MINE_COLS} FROM feedback f WHERE f.user_id=? ORDER BY f.id DESC LIMIT ? OFFSET ?", (uid, per_page, (page - 1) * per_page))
    return rows, total, page, pages


def get_for_user(fid, uid):
    """Detail milik uid; None bila bukan miliknya (route menjawab 404, tidak membocorkan keberadaan data)."""
    return query(f"SELECT {MINE_COLS} FROM feedback f WHERE f.id=? AND f.user_id=?", (fid, uid), one=True)


def history_for_user(fid):
    """Riwayat status untuk pemilik: tanpa catatan internal. Nama petugas disamarkan menjadi 'Satpam'."""
    return query("SELECT h.old_status, h.new_status, h.created_at FROM feedback_history h WHERE h.feedback_id=? ORDER BY h.id DESC", (fid,))


def unread_count(uid):
    """Jumlah masukan milik uid yang punya pembaruan Satpam (status/tanggapan) yang belum dilihat."""
    return query("SELECT COUNT(*) n FROM feedback WHERE user_id=? AND rev>student_seen_rev", (uid,), one=True)["n"]


def mark_seen(fid, uid):
    """Tandai sudah dibaca (hanya oleh pemilik)."""
    execute("UPDATE feedback SET student_seen_rev=rev WHERE id=? AND user_id=? AND student_seen_rev<rev", (fid, uid))


# ---- balasan pengirim (mahasiswa) ----
MAX_STUDENT_STREAK = 3      # maksimal balasan beruntun tanpa tanggapan Satpam di antaranya


def reply_state(fid):
    """(sudah_ditanggapi_satpam, jumlah_balasan_pengirim_beruntun_terakhir)."""
    staff, streak = False, 0
    for r in query("SELECT from_student FROM feedback_responses WHERE feedback_id=? ORDER BY id DESC", (fid,)):
        if r["from_student"]:
            streak += 1
        else:
            staff = True
            break
    return staff, streak


def can_reply(fid):
    """(boleh, alasan). Pengirim hanya bisa membalas setelah Satpam menanggapi, dan tidak lebih dari MAX_STUDENT_STREAK kali beruntun."""
    staff, streak = reply_state(fid)
    if not staff:
        return False, "Kamu dapat membalas setelah Satpam memberikan tanggapan."
    if streak >= MAX_STUDENT_STREAK:
        return False, "Balasanmu sudah terkirim. Tunggu tanggapan Satpam sebelum membalas lagi."
    return True, ""


def last_student_reply(fid):
    r = query("SELECT message FROM feedback_responses WHERE feedback_id=? AND from_student=1 ORDER BY id DESC LIMIT 1", (fid,), one=True)
    return r["message"] if r else None


def add_student_reply(fid, uid, message):
    """Balasan pemilik laporan. Tidak mengubah status/rev (itu wilayah Satpam); hanya menaikkan srev agar Satpam diberi tahu."""
    db = get_db()
    cur = db.execute("INSERT INTO feedback_responses(feedback_id,message,created_by,from_student) VALUES (?,?,?,1)", (fid, message, uid))
    db.execute("UPDATE feedback SET srev=srev+1 WHERE id=?", (fid,))
    db.commit()
    return cur.lastrowid


def staff_unread_count(demo_only=False):
    """Jumlah masukan yang punya balasan pengirim yang belum dibuka Satpam."""
    return query("SELECT COUNT(*) n FROM feedback f WHERE f.srev>f.staff_seen_srev" + (" AND f.is_demo=1" if demo_only else ""), one=True)["n"]


def mark_staff_seen(fid):
    execute("UPDATE feedback SET staff_seen_srev=srev WHERE id=? AND staff_seen_srev<srev", (fid,))
