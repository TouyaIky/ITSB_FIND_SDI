import os
from datetime import date

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_from_directory, url_for)

from config import settings as S
from config.settings import FEEDBACK_CATEGORIES, FEEDBACK_REPLY_TEMPLATES, FEEDBACK_STATUSES, USER_TYPES
from models import activity as ACT, feedback as F, found_item as FI, lost_item as LI, returns as R
from services.image_validation import save_valid_image
from services.matching import count_candidates
from services.report_form import read_report_form
from services.security import demo_scope, role_required, valid_phone

bp = Blueprint("satpam", __name__, url_prefix="/satpam")
OWNER_TYPES = dict(USER_TYPES)


@bp.route("/")
@role_required("security")
def dashboard():
    d = demo_scope()
    found, lost = FI.counts(d), LI.counts(d)
    return render_template("satpam/dashboard.html", found=found, lost=lost, activity=ACT.recent(8, d),
                           pending=FI.staff_list("pending", d)[:8], fb=F.stats(d), fb_unanswered=F.unanswered(d), fb_reply_unread=F.staff_unread_count(d), kinds=ACT.KINDS)


@bp.route("/found")
@role_required("security")
def found():
    status = request.args.get("status", "")
    return render_template("satpam/found.html", items=FI.staff_list(status, demo_scope()), status=status)


@bp.route("/found/<int:fid>/confirm", methods=["POST"])
@role_required("security")
def confirm(fid):
    if not FI.get_staff(fid, demo_scope()):
        abort(404)
    if FI.confirm_receipt(fid, g.user["id"], demo_scope()):
        flash("Penerimaan barang dikonfirmasi. Barang kini tampil di Daftar Barang Temuan.", "success")
    else:
        flash("Barang ini sudah dikonfirmasi sebelumnya.", "info")
    return redirect(request.referrer or url_for("satpam.found"))


def _reason_error(status, reason):
    """Alasan wajib (min. 5 karakter) saat menolak laporan; alasan terlihat oleh pelapor."""
    if status == "declined" and len(reason) < 5:
        return "Alasan penolakan wajib diisi (minimal 5 karakter)."
    if len(reason) > 500:
        return "Catatan terlalu panjang (maksimal 500 karakter)."
    return None


@bp.route("/found/<int:fid>/status", methods=["POST"])
@role_required("security")
def found_status(fid):
    """Ubah status laporan temuan: pending | stored | declined. 'Sudah dikembalikan' hanya lewat proses pengembalian."""
    item = FI.get_staff(fid, demo_scope())
    if not item:
        abort(404)
    status, reason = request.form.get("status", ""), request.form.get("reason", "").strip()
    if status not in FI.STAFF_STATUSES:
        flash("Status tidak valid.", "error")
    elif item["status"] == "returned":
        flash("Barang yang sudah dikembalikan tidak dapat diubah statusnya.", "error")
    elif (err := _reason_error(status, reason)):
        flash(err, "error")
    elif FI.set_status(fid, status, g.user["id"], reason, demo_scope()):
        flash("Status laporan diperbarui.", "success")
    else:
        flash("Status tidak berubah.", "info")
    return redirect(request.referrer or url_for("satpam.found"))


def _drop_photo(name, folder=None):
    if name:
        try:
            os.remove(os.path.join(folder or current_app.config["UPLOAD_FOLDER"], os.path.basename(name)))
        except OSError:
            pass


def _edit(kind, rid):
    model = FI if kind == "found" else LI
    item = model.get_staff(rid, demo_scope()) if kind == "found" else LI.get(rid, demo_scope())
    if not item:
        abort(404)
    if kind == "found" and item["status"] == "returned":
        flash("Barang yang sudah dikembalikan tidak dapat diedit.", "error")
        return redirect(url_for("satpam.found"))
    back = url_for("satpam.found" if kind == "found" else "satpam.lost")
    d = {"item_name": item["item_name"], "category": item["category"], "description": item["description"], "location": item["location"],
         "date": item["date_found" if kind == "found" else "date_lost"], "time": item["time_found" if kind == "found" else "time_lost"],
         "phone": item["reporter_phone"]}
    if request.method == "POST":
        d, err = read_report_form()
        if err:
            flash(err, "error")
        elif model.update_info(rid, d, demo_scope()):
            flash("Informasi laporan diperbarui.", "success")
            return redirect(back)
        else:
            flash("Laporan tidak dapat diperbarui.", "error")
    return render_template("satpam/report_edit.html", kind=kind, item=item, d=d, back=back, categories=S.CATEGORIES,
                           suggestions=S.LOCATION_SUGGESTIONS, today=date.today().isoformat())


@bp.route("/found/<int:fid>/edit", methods=["GET", "POST"])
@role_required("security")
def found_edit(fid):
    return _edit("found", fid)


@bp.route("/found/<int:fid>/delete", methods=["POST"])
@role_required("security")
def found_delete(fid):
    photo = FI.delete(fid, demo_scope())
    if photo is None:
        flash("Laporan tidak ditemukan atau sudah dikembalikan sehingga tidak dapat dihapus.", "error")
    else:
        _drop_photo(photo)
        flash("Laporan dihapus.", "success")
    return redirect(url_for("satpam.found"))


@bp.route("/lost")
@role_required("security")
def lost():
    status = request.args.get("status", "")
    stored = FI.stored_for_matching()
    rows = [dict(r) for r in LI.staff_list(status, demo_scope())]
    for r in rows:
        r["candidates"] = count_candidates(r, stored) if r["status"] == "open" else 0
    return render_template("satpam/lost.html", items=rows, status=status)


@bp.route("/lost/<int:lid>/resolve", methods=["POST"])
@role_required("security")
def lost_resolve(lid):
    if not LI.get(lid, demo_scope()):
        abort(404)
    LI.resolve(lid, demo_only=demo_scope())
    flash("Laporan kehilangan ditandai selesai.", "success")
    return redirect(url_for("satpam.lost"))


@bp.route("/lost/<int:lid>/status", methods=["POST"])
@role_required("security")
def lost_status(lid):
    """Ubah status laporan kehilangan: open | resolved | declined (ditolak, alasan wajib)."""
    if not LI.get(lid, demo_scope()):
        abort(404)
    status, reason = request.form.get("status", ""), request.form.get("reason", "").strip()
    if status not in LI.STAFF_STATUSES:
        flash("Status tidak valid.", "error")
    elif (err := _reason_error(status, reason)):
        flash(err, "error")
    elif LI.set_status(lid, status, g.user["id"], reason, demo_scope()):
        flash("Status laporan diperbarui.", "success")
    else:
        flash("Status tidak berubah.", "info")
    return redirect(request.referrer or url_for("satpam.lost"))


@bp.route("/lost/<int:lid>/edit", methods=["GET", "POST"])
@role_required("security")
def lost_edit(lid):
    return _edit("lost", lid)


@bp.route("/lost/<int:lid>/delete", methods=["POST"])
@role_required("security")
def lost_delete(lid):
    photo = LI.delete(lid, demo_scope())
    if photo is None:
        flash("Laporan tidak ditemukan.", "error")
    else:
        _drop_photo(photo)
        flash("Laporan dihapus.", "success")
    return redirect(url_for("satpam.lost"))


# ---------- Pengembalian barang (dilakukan langsung di pos Satpam) ----------
@bp.route("/returns")
@role_required("security")
def returns():
    q = request.args.get("q", "").strip()
    return render_template("satpam/returns.html", items=FI.search_stored(q, demo_scope()), q=q)


@bp.route("/returns/<int:fid>", methods=["GET", "POST"])
@role_required("security")
def return_item(fid):
    item = FI.get_staff(fid, demo_scope())
    if not item:
        abort(404)
    if item["status"] != "stored":
        flash("Barang ini tidak dalam status disimpan, jadi tidak dapat dikembalikan.", "error")
        return redirect(url_for("satpam.returns"))
    d = {"owner_type": "student"}
    if request.method == "POST":
        d = {k: request.form.get(k, "").strip() for k in ("owner_name", "owner_type", "owner_phone", "notes")}
        phone, err = valid_phone(d["owner_phone"])
        if not (d["owner_name"] and d["notes"]):
            err = "Nama pemilik dan catatan verifikasi kepemilikan wajib diisi."
        elif d["owner_type"] not in OWNER_TYPES:
            err = "Pilih jenis pengguna pemilik."
        elif len(d["owner_name"]) > 100 or len(d["notes"]) > 500:
            err = "Isian terlalu panjang."
        photo = None
        if not err:
            photo, err = save_valid_image(request.files.get("photo"), current_app.config["PRIVATE_UPLOAD_FOLDER"],
                                          current_app.config["MAX_IMAGE_BYTES"], current_app.config["ALLOWED_IMAGE_EXT"], True)
        if err:
            flash(err, "error")
        else:
            try:
                ok = R.create(fid, d["owner_name"], d["owner_type"], phone, g.user["id"], photo, d["notes"])
            except Exception:
                ok = False
            if ok:
                flash("Pengembalian dikonfirmasi. Status barang: Sudah Dikembalikan.", "success")
                return redirect(url_for("satpam.history"))
            try:
                os.remove(os.path.join(current_app.config["PRIVATE_UPLOAD_FOLDER"], photo))
            except OSError:
                pass
            flash("Pengembalian gagal diproses. Barang mungkin sudah dikembalikan.", "error")
            return redirect(url_for("satpam.returns"))
    return render_template("satpam/return_form.html", item=item, d=d, owner_types=USER_TYPES)


@bp.route("/history")
@role_required("security")
def history():
    return render_template("satpam/history.html", rows=R.all_rows(demo_scope()))


@bp.route("/return-photo/<int:rid>")
@role_required("security")
def return_photo(rid):
    """Foto dokumentasi hanya bisa diambil lewat route ini (dicek role di backend). Foto tidak berada di folder static."""
    row = R.get(rid, demo_scope())
    if not row or not row["documentation_photo"]:
        abort(404)
    resp = send_from_directory(current_app.config["PRIVATE_UPLOAD_FOLDER"], row["documentation_photo"])
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@bp.route("/activity")
@role_required("security")
def activity():
    page = request.args.get("page", 1, type=int) or 1
    rows, total, page, pages = ACT.page(page, 20, demo_scope())
    return render_template("satpam/activity.html", rows=rows, total=total, page=page, pages=pages, kinds=ACT.KINDS)


# ---------- Kritik dan Saran: tindak lanjut ----------
@bp.route("/feedback")
@role_required("security")
def feedback():
    f = {k: request.args.get(k, "").strip() for k in ("q", "status", "category", "resp")}
    sort = "oldest" if request.args.get("sort") == "oldest" else "newest"
    page = request.args.get("page", 1, type=int) or 1
    rows, total, page, pages = F.search(f["q"], f["status"], f["category"], sort, page, demo_scope(), f["resp"])
    args = {k: v for k, v in {**f, "sort": sort}.items() if v}
    return render_template("satpam/feedback.html", rows=rows, total=total, page=page, pages=pages, f=f, sort=sort, args=args,
                           stats=F.stats(demo_scope()), unanswered=F.unanswered(demo_scope()), reply_unread=F.staff_unread_count(demo_scope()), categories=FEEDBACK_CATEGORIES, statuses=FEEDBACK_STATUSES)


@bp.route("/feedback/<int:fid>")
@role_required("security")
def feedback_detail(fid):
    item = F.get(fid, demo_scope())
    if not item:
        abort(404)
    F.mark_staff_seen(fid)         # Satpam membuka laporan -> penanda "balasan baru" dianggap dibaca
    return render_template("satpam/feedback_detail.html", item=item, history=F.history(fid), responses=F.responses(fid), statuses=FEEDBACK_STATUSES, reply_templates=FEEDBACK_REPLY_TEMPLATES)


def _wants_json():
    """Request dari JavaScript (fetch) meminta JSON; form biasa tetap memakai redirect + flash (fallback tanpa JS)."""
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


def _view_dicts(fid):
    """Snapshot terbaru (status, riwayat, tanggapan) untuk memperbarui tampilan tanpa reload."""
    f = current_app.jinja_env.filters
    item = F.get(fid)
    return {
        "status": item["status"], "label": f["status_label"](item["status"]), "cls": f["status_cls"](item["status"]),
        "updated_at": f["idt"](item["updated_at"]) if item["updated_at"] else "",
        "handler": item["handler"] or "",
        "history": [{"old_label": f["status_label"](h["old_status"]) if h["old_status"] else "", "old_cls": f["status_cls"](h["old_status"]) if h["old_status"] else "",
                     "new_label": f["status_label"](h["new_status"]), "new_cls": f["status_cls"](h["new_status"]),
                     "at": f["idt"](h["created_at"]), "actor": h["actor"] or ("Sistem" if not h["old_status"] else "-"), "note": h["note"] or ""}
                    for h in F.history(fid)],
        "responses": [{"officer": r["officer"] or ("Pengirim" if r["from_student"] else "Satpam"), "from_student": bool(r["from_student"]),
                       "at": f["idt"](r["created_at"]), "message": r["message"]} for r in F.responses(fid)],
    }


def _reply(fid, ok, message, category, code=200, anchor=""):
    if _wants_json():
        return jsonify(ok=ok, message=message, **(_view_dicts(fid) if ok else {})), (code if not ok else 200)
    flash(message, category)
    return redirect(url_for("satpam.feedback_detail", fid=fid) + anchor)


@bp.route("/feedback/<int:fid>/status", methods=["POST"])
@role_required("security")
def feedback_status(fid):
    if not F.get(fid, demo_scope()):
        abort(404)
    d = request.get_json(silent=True) or request.form
    status, reason = (d.get("status") or "").strip(), (d.get("reason") or "").strip()
    if status not in F.STATUS_CODES:
        return _reply(fid, False, "Status tidak valid.", "error", 400)
    if status == "rejected" and len(reason) < 5:
        return _reply(fid, False, "Alasan wajib diisi (minimal 5 karakter) untuk status Tidak Dapat Ditindaklanjuti.", "error", 400)
    if len(reason) > 500:
        return _reply(fid, False, "Catatan terlalu panjang (maksimal 500 karakter).", "error", 400)
    if not F.change_status(fid, status, g.user["id"], reason):
        return _reply(fid, False, "Status tidak berubah.", "info", 409)
    if status == "rejected":        # alasan penolakan juga menjadi tanggapan yang terlihat oleh pengirim
        F.add_response(fid, g.user["id"], reason)
    return _reply(fid, True, "Status tindak lanjut diperbarui.", "success")


@bp.route("/feedback/<int:fid>/respond", methods=["POST"])
@role_required("security")
def feedback_respond(fid):
    """Kirim tanggapan (pertama atau tambahan) kepada pengirim. Setiap kiriman = baris baru, tidak menimpa tanggapan lama."""
    if not F.get(fid, demo_scope()):
        abort(404)
    d = request.get_json(silent=True) or request.form
    msg, new_status = (d.get("response") or "").strip(), (d.get("status") or "").strip()
    if len(msg) < 3:
        return _reply(fid, False, "Tanggapan wajib diisi (minimal 3 karakter).", "error", 400, "#tanggapan")
    if len(msg) > 1000:
        return _reply(fid, False, "Tanggapan terlalu panjang (maksimal 1000 karakter).", "error", 400, "#tanggapan")
    changed = False
    if new_status:                      # opsional: ubah status sekaligus dengan satu tombol
        if new_status not in F.STATUS_CODES:
            return _reply(fid, False, "Status tidak valid.", "error", 400)
        if new_status == "rejected" and len(msg) < 5:
            return _reply(fid, False, "Alasan wajib diisi (minimal 5 karakter) untuk status Tidak Dapat Ditindaklanjuti.", "error", 400, "#tanggapan")
        if new_status != F.get(fid)["status"]:      # status sama = hanya kirim tanggapan, bukan error
            changed = F.change_status(fid, new_status, g.user["id"], msg if new_status == "rejected" else "")
    F.add_response(fid, g.user["id"], msg)         # tanggapan selalu baris baru (alasan penolakan = tanggapan ini juga)
    return _reply(fid, True, "Status diperbarui dan tanggapan terkirim." if changed else "Tanggapan terkirim dan dapat dilihat oleh pengirim.", "success", anchor="#tanggapan")


@bp.route("/feedback/<int:fid>/note", methods=["POST"])
@role_required("security")
def feedback_note(fid):
    if not F.get(fid, demo_scope()):
        abort(404)
    note = request.form.get("note", "").strip()
    if len(note) > 1000:
        flash("Catatan internal terlalu panjang (maksimal 1000 karakter).", "error")
    else:
        F.set_note(fid, note, g.user["id"])
        flash("Catatan internal disimpan.", "success")
    return redirect(url_for("satpam.feedback_detail", fid=fid))
