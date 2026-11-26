"""Laporan kehilangan. Status: open (belum ditemukan) | resolved (selesai) | declined (ditolak Satpam).
Status TIDAK berubah otomatis walau ada barang temuan yang mirip."""
from database.db import execute, get_db, query

PUBLIC = "l.id,l.item_name,l.category,l.description,l.location,l.date_lost,l.time_lost,l.photo,l.status,l.created_at,l.is_demo"
PUBLIC_VIEW = f"SELECT {PUBLIC} FROM lost_items l"
STAFF_VIEW = "SELECT l.*, u.name AS reporter, u.role AS reporter_role, u.nim FROM lost_items l JOIN users u ON u.id=l.user_id"
STAFF_STATUSES = ("open", "resolved", "declined")


def create(user_id, d, photo, is_demo=0):
    return execute(
        "INSERT INTO lost_items(user_id,item_name,category,description,location,date_lost,time_lost,photo,reporter_phone,is_demo)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user_id, d["item_name"], d["category"], d["description"], d["location"], d["date"], d["time"], photo, d["phone"], is_demo))


def get(lid, demo_only=False):
    return query("SELECT l.*, u.name AS reporter FROM lost_items l JOIN users u ON u.id=l.user_id WHERE l.id=?" + (" AND l.is_demo=1" if demo_only else ""), (lid,), one=True)


def public_list(q="", category="", location="", date_from="", date_to="", status="", sort="newest"):
    sql = PUBLIC_VIEW + " WHERE l.status!='declined'"          # laporan yang ditolak Satpam tidak tampil publik
    args = []
    if q:
        sql += " AND (l.item_name LIKE ? OR l.description LIKE ? OR l.location LIKE ?)"; args += [f"%{q}%"] * 3
    if category:
        sql += " AND l.category=?"; args.append(category)
    if location:
        sql += " AND l.location=?"; args.append(location)
    if date_from:
        sql += " AND l.date_lost>=?"; args.append(date_from)
    if date_to:
        sql += " AND l.date_lost<=?"; args.append(date_to)
    if status == "resolved":
        sql += " AND l.status='resolved'"
    elif status in ("open", "candidates"):
        sql += " AND l.status='open'"           # 'candidates' disaring lagi di route (butuh skor kemiripan)
    sql += " ORDER BY l.date_lost ASC, l.id ASC" if sort == "oldest" else " ORDER BY l.date_lost DESC, l.id DESC"
    return query(sql, args)


def locations():
    return [r["location"] for r in query("SELECT DISTINCT location FROM lost_items WHERE status!='declined' ORDER BY location")]


def by_user(uid):
    return query("SELECT * FROM lost_items WHERE user_id=? ORDER BY id DESC", (uid,))


def staff_list(status="", demo_only=False):
    where, args = ["1=1"], []
    if status in STAFF_STATUSES:
        where.append("l.status=?"); args.append(status)
    if demo_only:
        where.append("l.is_demo=1")
    return query(STAFF_VIEW + " WHERE " + " AND ".join(where) + " ORDER BY l.id DESC", args)


def resolve(lid, user_id=None, demo_only=False):
    """Tandai selesai. user_id diisi untuk pemilik laporan; None untuk Satpam. Laporan yang ditolak tidak bisa 'dihidupkan' lewat sini."""
    if user_id is None:
        execute("UPDATE lost_items SET status='resolved', updated_at=datetime('now','localtime') WHERE id=? AND status='open'"
                + (" AND is_demo=1" if demo_only else ""), (lid,))
    else:
        execute("UPDATE lost_items SET status='resolved', updated_at=datetime('now','localtime') WHERE id=? AND user_id=? AND status='open'", (lid, user_id))


def set_status(lid, status, officer_id, note="", demo_only=False):
    """Ubah status oleh Satpam: open | resolved | declined (alasan wajib divalidasi di route)."""
    if status not in STAFF_STATUSES:
        return False
    db = get_db()
    row = db.execute("SELECT status FROM lost_items WHERE id=?" + (" AND is_demo=1" if demo_only else ""), (lid,)).fetchone()
    if row is None or row["status"] == status:
        return False
    db.execute("UPDATE lost_items SET status=?, reviewed_by=?, reviewed_at=datetime('now','localtime'), review_note=?,"
               " updated_at=datetime('now','localtime') WHERE id=?", (status, officer_id, (note or None) if status == "declined" else None, lid))
    db.commit()
    return True


def update_info(lid, d, demo_only=False):
    db = get_db()
    cur = db.execute("UPDATE lost_items SET item_name=?, category=?, description=?, location=?, date_lost=?, time_lost=?,"
                     " reporter_phone=?, updated_at=datetime('now','localtime') WHERE id=?" + (" AND is_demo=1" if demo_only else ""),
                     (d["item_name"], d["category"], d["description"], d["location"], d["date"], d["time"], d["phone"], lid))
    db.commit()
    return cur.rowcount == 1


def delete(lid, demo_only=False):
    """Hapus laporan tidak valid. Return nama foto (boleh kosong) atau None jika tidak ada."""
    db = get_db()
    row = db.execute("SELECT photo FROM lost_items WHERE id=?" + (" AND is_demo=1" if demo_only else ""), (lid,)).fetchone()
    if row is None:
        return None
    db.execute("DELETE FROM lost_items WHERE id=?", (lid,))
    db.commit()
    return row["photo"] or ""


def counts(demo_only=False):
    r = query("SELECT COUNT(*) all_reports, SUM(status='open') open, SUM(status='resolved') resolved, SUM(status='declined') declined"
              " FROM lost_items" + (" WHERE is_demo=1" if demo_only else ""), one=True)
    c = {k: (r[k] or 0) for k in r.keys()}
    c["total"] = c["all_reports"] - c["declined"]
    return c
