from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from config.settings import FEEDBACK_CATEGORIES
from models import feedback as F
from services.i18n import tr
from services.security import EMAIL_RE, client_ip, login_required, rate_limited

bp = Blueprint("feedback", __name__)


@bp.route("/feedback")
def page():
    mine = F.latest_by_user(g.user["id"], 5) if g.user and g.user["role"] != "security" else []
    return render_template("feedback.html", feedback_categories=FEEDBACK_CATEGORIES, mine=mine)


def _student_only():
    if g.user["role"] == "security":      # Satpam mengelola lewat /satpam/feedback, bukan riwayat pengirim
        abort(403)


@bp.route("/feedback/mine")
@login_required
def mine():
    """Riwayat lengkap kritik & saran milik pengguna yang login (dipaginasi)."""
    _student_only()
    rows, total, page, pages = F.page_by_user(g.user["id"], request.args.get("page", 1, type=int) or 1)
    return render_template("feedback_mine.html", rows=rows, total=total, page=page, pages=pages)


@bp.route("/feedback/mine/<int:fid>")
@login_required
def mine_detail(fid):
    _student_only()
    item = F.get_for_user(fid, g.user["id"])
    if not item:
        abort(404)
    F.mark_seen(fid, g.user["id"])      # pemilik membuka laporan -> notifikasi dianggap dibaca
    ok, hint = F.can_reply(fid)
    return render_template("feedback_mine_detail.html", item=item, responses=F.responses(fid), history=F.history_for_user(fid), can_reply=ok, reply_hint=hint)


def _thread(fid):
    """Snapshot percakapan untuk pemilik (dipakai JS agar tampilan = isi database). Catatan internal tidak pernah ikut."""
    idt = current_app.jinja_env.filters["idt"]
    ok, hint = F.can_reply(fid)
    rs = F.responses(fid)
    return {"responses": [{"mine": bool(r["from_student"]), "author": tr("Kamu") if r["from_student"] else tr("Satpam"),
                           "at": idt(r["created_at"]), "message": r["message"]} for r in rs],
            "count": len(rs), "can_reply": ok, "reply_hint": tr(hint) if hint else ""}


@bp.route("/feedback/mine/<int:fid>/reply", methods=["POST"])
@login_required
def reply(fid):
    """Pemilik laporan membalas tanggapan Satpam. JSON untuk fetch; form biasa memakai redirect + flash (fallback tanpa JS)."""
    _student_only()
    if not F.get_for_user(fid, g.user["id"]):
        abort(404)                                   # bukan miliknya = tidak ada
    wants_json = request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"

    def out(ok, message, code=200, category="error"):
        if wants_json:
            return jsonify(ok=ok, message=message, **(_thread(fid) if ok else {})), code
        flash(message, "success" if ok else category)
        return redirect(url_for("feedback.mine_detail", fid=fid) + "#tanggapan")

    d = request.get_json(silent=True) or request.form
    msg = (d.get("response") or "").strip()
    if len(msg) < 3:
        return out(False, "Balasan wajib diisi (minimal 3 karakter).", 400)
    if len(msg) > 1000:
        return out(False, "Balasan terlalu panjang (maksimal 1000 karakter).", 400)
    allowed, hint = F.can_reply(fid)
    if not allowed:
        return out(False, hint, 409)
    if F.last_student_reply(fid) == msg:
        return out(False, "Balasan yang sama baru saja dikirim.", 409)
    if rate_limited(f"fbr:u{g.user['id']}", 5, 600):
        return out(False, "Terlalu banyak balasan. Coba lagi beberapa menit lagi.", 429)
    F.add_student_reply(fid, g.user["id"], msg)
    return out(True, "Balasan terkirim. Satpam akan melihatnya.")


@bp.route("/feedback/send", methods=["POST"])
def send():
    d = request.get_json(silent=True) or request.form
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip()
    category = (d.get("category") or "").strip()
    subject = (d.get("subject") or "").strip()
    message = (d.get("message") or "").strip()
    if g.user:   # data akun dipakai untuk pengguna yang login
        name, email = g.user["name"], g.user["email"]

    def fail(msg, code=400):
        return jsonify(ok=False, message=msg), code

    # Batas per akun untuk pengguna login (Wi-Fi kampus berbagi satu IP); per IP hanya untuk pengunjung tanpa akun.
    key, limit = (f"fb:u{g.user['id']}", 5) if g.user else (f"fb:ip:{client_ip()}", 3)
    if rate_limited(key, limit, 600):
        return fail("Terlalu banyak pengiriman. Coba lagi beberapa menit lagi.", 429)
    if not all([name, email, category, subject, message]):
        return fail("Semua kolom wajib diisi.")
    if not 2 <= len(name) <= 80:
        return fail("Nama harus 2–80 karakter.")
    if not EMAIL_RE.match(email):
        return fail("Format email tidak valid.")
    if category not in FEEDBACK_CATEGORIES:
        return fail("Kategori tidak valid.")
    if not 3 <= len(subject) <= 120:
        return fail("Subjek harus 3–120 karakter.")
    if not 10 <= len(message) <= 1500:
        return fail("Pesan harus 10–1500 karakter.")
    if F.recent_duplicate(email, message):
        return fail("Pesan yang sama baru saja dikirim.", 429)

    F.create(g.user["id"] if g.user else None, name, email, category, subject, message, g.user["is_demo"] if g.user else 0)
    # Masukan hanya masuk ke dashboard Satpam (tidak dikirim lewat email).
    return jsonify(ok=True, status="saved", message="Terima kasih! Masukan Anda sudah tersimpan dan akan ditinjau oleh Satpam.")
