"""Riwayat aktivitas seluruh sistem untuk Satpam. Tidak ada tabel log terpisah: semuanya dihitung dari data nyata,
sehingga bila belum ada aktivitas hasilnya benar-benar kosong."""
from database.db import query

KINDS = {   # kode: (label ID, ikon lucide)
    "found_reported": ("Laporan barang temuan", "package-plus"),
    "lost_reported": ("Laporan barang hilang", "search-x"),
    "found_verified": ("Penerimaan barang dikonfirmasi", "badge-check"),
    "found_declined": ("Laporan barang temuan ditolak", "circle-x"),
    "lost_declined": ("Laporan barang hilang ditolak", "circle-x"),
    "returned": ("Barang dikembalikan", "hand-helping"),
    "feedback_sent": ("Kritik dan saran masuk", "message-square-text"),
    "feedback_status": ("Status kritik dan saran diubah", "refresh-cw"),
    "feedback_response": ("Tanggapan kritik dan saran dikirim", "message-circle-reply"),
}


def _sql(demo_only):
    f = " AND f.is_demo=1" if demo_only else ""
    l = " AND l.is_demo=1" if demo_only else ""
    fb = " AND fb.is_demo=1" if demo_only else ""
    return f"""
SELECT 'found_reported' kind, f.item_name name, u.name actor, f.status status, f.created_at ts FROM found_items f JOIN users u ON u.id=f.user_id WHERE 1=1{f}
UNION ALL SELECT 'lost_reported', l.item_name, u.name, l.status, l.created_at FROM lost_items l JOIN users u ON u.id=l.user_id WHERE 1=1{l}
UNION ALL SELECT 'found_verified', f.item_name, o.name, 'stored', f.received_at FROM found_items f JOIN users o ON o.id=f.received_by WHERE f.received_at IS NOT NULL{f}
UNION ALL SELECT 'found_declined', f.item_name, o.name, 'declined', f.reviewed_at FROM found_items f JOIN users o ON o.id=f.reviewed_by WHERE f.status='declined' AND f.reviewed_at IS NOT NULL{f}
UNION ALL SELECT 'lost_declined', l.item_name, o.name, 'declined', l.reviewed_at FROM lost_items l JOIN users o ON o.id=l.reviewed_by WHERE l.status='declined' AND l.reviewed_at IS NOT NULL{l}
UNION ALL SELECT 'returned', f.item_name, o.name, 'returned', r.return_date FROM item_returns r JOIN found_items f ON f.id=r.found_item_id JOIN users o ON o.id=r.officer_id WHERE 1=1{f}
UNION ALL SELECT 'feedback_sent', fb.subject, fb.sender_name, 'new', fb.created_at FROM feedback fb WHERE 1=1{fb}
UNION ALL SELECT 'feedback_status', fb.subject, COALESCE(o.name,'-'), h.new_status, h.created_at FROM feedback_history h JOIN feedback fb ON fb.id=h.feedback_id LEFT JOIN users o ON o.id=h.changed_by WHERE h.old_status IS NOT NULL{fb}
UNION ALL SELECT 'feedback_response', fb.subject, COALESCE(o.name,'-'), fb.status, r.created_at FROM feedback_responses r JOIN feedback fb ON fb.id=r.feedback_id LEFT JOIN users o ON o.id=r.created_by WHERE 1=1{fb}
"""


def page(page=1, per_page=20, demo_only=False):
    base = _sql(demo_only)
    total = query(f"SELECT COUNT(*) n FROM ({base})", one=True)["n"]
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    rows = query(f"SELECT * FROM ({base}) WHERE ts IS NOT NULL ORDER BY ts DESC LIMIT ? OFFSET ?", (per_page, (page - 1) * per_page))
    return rows, total, page, pages


def recent(limit=8, demo_only=False):
    return query(f"SELECT * FROM ({_sql(demo_only)}) WHERE ts IS NOT NULL ORDER BY ts DESC LIMIT ?", (limit,))
