"""Barang temuan. Status: pending (menunggu penyerahan) | stored (disimpan Satpam) | returned (sudah dikembalikan)
| declined (ditolak Satpam; tidak pernah tampil di daftar publik).
Kolom publik ditulis eksplisit: reporter_phone TIDAK PERNAH ikut dipilih pada query publik."""
from database.db import execute, get_db, query

PUBLIC = "f.id,f.item_name,f.category,f.description,f.location,f.date_found,f.time_found,f.photo,f.status,f.received_at,f.created_at,f.is_demo"
PUBLIC_VIEW = f"SELECT {PUBLIC} FROM found_items f"
STAFF_VIEW = "SELECT f.*, u.name AS reporter, u.role AS reporter_role FROM found_items f JOIN users u ON u.id=f.user_id"
STAFF_STATUSES = ("pending", "stored", "declined")      # 'returned' hanya lewat proses pengembalian


def create(user_id, d, photo, is_demo=0):
    return execute(
        "INSERT INTO found_items(user_id,item_name,category,description,location,date_found,time_found,photo,reporter_phone,is_demo)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user_id, d["item_name"], d["category"], d["description"], d["location"], d["date"], d["time"], photo, d["phone"], is_demo))


def get_staff(fid, demo_only=False):
    return query(STAFF_VIEW + " WHERE f.id=?" + (" AND f.is_demo=1" if demo_only else ""), (fid,), one=True)


def stored_for_matching():
    return query(f"SELECT {PUBLIC} FROM found_items f WHERE f.status='stored'")


def public_list(q="", category="", location="", date_from="", date_to="", status="", sort="newest"):
    sql = PUBLIC_VIEW + " WHERE f.status IN ('stored','returned')"
    args = []
    if q:
        sql += " AND (f.item_name LIKE ? OR f.description LIKE ? OR f.location LIKE ?)"; args += [f"%{q}%"] * 3
    if category:
        sql += " AND f.category=?"; args.append(category)
    if location:
        sql += " AND f.location=?"; args.append(location)
    if date_from:
        sql += " AND f.date_found>=?"; args.append(date_from)
    if date_to:
        sql += " AND f.date_found<=?"; args.append(date_to)
    if status in ("stored", "returned"):
        sql += " AND f.status=?"; args.append(status)
    sql += " ORDER BY f.date_found ASC, f.id ASC" if sort == "oldest" else " ORDER BY f.date_found DESC, f.id DESC"
    return query(sql, args)


def locations():
    return [r["location"] for r in query(
        "SELECT DISTINCT location FROM found_items WHERE status IN ('stored','returned') ORDER BY location")]


def by_user(uid):
    return query("SELECT * FROM found_items WHERE user_id=? ORDER BY id DESC", (uid,))


def staff_list(status="", demo_only=False):
    where, args = ["1=1"], []
    if status in ("pending", "stored", "returned", "declined"):
        where.append("f.status=?"); args.append(status)
    if demo_only:
        where.append("f.is_demo=1")
    return query(STAFF_VIEW + " WHERE " + " AND ".join(where) +
                 " ORDER BY CASE f.status WHEN 'pending' THEN 0 WHEN 'stored' THEN 1 WHEN 'returned' THEN 2 ELSE 3 END, f.id DESC", args)


def search_stored(q="", demo_only=False):
    sql = STAFF_VIEW + " WHERE f.status='stored'" + (" AND f.is_demo=1" if demo_only else "")
    args = []
    if q:
        sql += " AND (f.item_name LIKE ? OR f.id=?)"
        args = [f"%{q}%", int(q) if q.isdigit() else -1]
    return query(sql + " ORDER BY f.id DESC LIMIT 50", args)


def confirm_receipt(fid, officer_id, demo_only=False):
    """Verifikasi: barang sudah diterima fisik. pending -> stored (sekali saja)."""
    db = get_db()
    cur = db.execute("UPDATE found_items SET status='stored', received_by=?, received_at=datetime('now','localtime'),"
                     " reviewed_by=?, reviewed_at=datetime('now','localtime'), review_note=NULL"
                     " WHERE id=? AND status='pending'" + (" AND is_demo=1" if demo_only else ""), (officer_id, officer_id, fid))
    db.commit()
    return cur.rowcount == 1


def set_status(fid, status, officer_id, note="", demo_only=False):
    """Ubah status oleh Satpam: pending | stored | declined. Barang yang sudah dikembalikan tidak dapat diubah."""
    if status not in STAFF_STATUSES:
        return False
    db = get_db()
    row = db.execute("SELECT status FROM found_items WHERE id=?" + (" AND is_demo=1" if demo_only else ""), (fid,)).fetchone()
    if row is None or row["status"] in ("returned", status):
        return False
    received = ("received_by=?, received_at=datetime('now','localtime')," if status == "stored" else "received_by=NULL, received_at=NULL,")
    args = ([officer_id] if status == "stored" else []) + [officer_id, (note or None) if status == "declined" else None, fid]
    db.execute(f"UPDATE found_items SET status='{status}', {received} reviewed_by=?, reviewed_at=datetime('now','localtime'),"
               " review_note=?, updated_at=datetime('now','localtime') WHERE id=?", args)
    db.commit()
    return True


def update_info(fid, d, demo_only=False):
    db = get_db()
    cur = db.execute("UPDATE found_items SET item_name=?, category=?, description=?, location=?, date_found=?, time_found=?,"
                     " reporter_phone=?, updated_at=datetime('now','localtime') WHERE id=?" + (" AND is_demo=1" if demo_only else ""),
                     (d["item_name"], d["category"], d["description"], d["location"], d["date"], d["time"], d["phone"], fid))
    db.commit()
    return cur.rowcount == 1


def delete(fid, demo_only=False):
    """Hapus laporan tidak valid. Return nama foto (untuk dihapus dari disk) atau None jika tidak boleh/tidak ada.
    Barang yang sudah dikembalikan tidak dapat dihapus agar riwayat pengembalian tetap utuh."""
    db = get_db()
    row = db.execute("SELECT photo, status FROM found_items WHERE id=?" + (" AND is_demo=1" if demo_only else ""), (fid,)).fetchone()
    if row is None or row["status"] == "returned":
        return None
    db.execute("DELETE FROM found_items WHERE id=?", (fid,))
    db.commit()
    return row["photo"] or ""


def counts(demo_only=False):
    r = query("SELECT COUNT(*) all_reports, SUM(status='stored') stored, SUM(status='returned') returned,"
              " SUM(status='pending') pending, SUM(status='declined') declined FROM found_items" + (" WHERE is_demo=1" if demo_only else ""), one=True)
    c = {k: (r[k] or 0) for k in r.keys()}
    c["received"] = c["stored"] + c["returned"]                  # barang yang sudah diterima Satpam (terverifikasi)
    c["total"] = c["all_reports"] - c["declined"]                # semua laporan yang tidak ditolak
    return c
