import os
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for

from config.settings import Config, CATEGORIES, ROLE_LABELS, production_warnings
from config import branding, team_members
from database.db import close_db
from database.init_db import init_db
from models import feedback as FB, user as U
from routes import auth, feedback, main, satpam, user
from flask import get_flashed_messages
from services.i18n import get_lang, js_strings, tr, translate_html
from services.security import check_csrf, csrf_token


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    init_db(app)
    app.teardown_appcontext(close_db)
    for msg in production_warnings(app.config):
        app.logger.warning("[KONFIGURASI] %s", msg)
    from services.email_service import env_file_status, missing
    if missing(app.config):
        _, found = env_file_status()
        app.logger.warning("[EMAILJS] belum lengkap, email Lupa Password tidak akan terkirim. Belum terisi: %s. File .env %s. "
                           "Cek dengan: python manage.py test-email EMAIL_ANDA",
                           ", ".join(missing(app.config)), "ditemukan" if found else "TIDAK ditemukan (nilai di .env.example tidak dibaca)")

    for m in (main, auth, user, feedback, satpam):
        app.register_blueprint(m.bp)

    @app.before_request
    def load_user():
        g.user = U.by_id(session["uid"]) if "uid" in session else None
        if g.user is None and "uid" in session:
            session.clear()
        g.guest = g.user is None
        if request.method == "POST":
            check_csrf()

    MONTHS = {"id": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
              "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}

    @app.template_filter("idate")
    def idate(v):
        try:
            y, m, d = str(v)[:10].split("-")
            return f"{int(d)} {MONTHS[get_lang()][int(m) - 1]} {y}"
        except Exception:
            return v or "-"

    @app.template_filter("idt")
    def idt(v):
        return f"{idate(v)}, {str(v)[11:16]}" if v and len(str(v)) >= 16 else idate(v)

    from config.settings import FEEDBACK_REPLY_TEMPLATES, FEEDBACK_STATUS_HELP, FEEDBACK_STATUSES
    STATUS = {c: (lbl, cls) for c, lbl, cls in FEEDBACK_STATUSES}
    STATUS.update({"pending": ("Menunggu Penyerahan", "b-pending"), "stored": ("Belum Dikembalikan", "b-stored"),
              "returned": ("Sudah Dikembalikan", "b-returned"), "open": ("Belum Ditemukan", "b-lost"),
              "resolved": ("Selesai", "b-returned"), "declined": ("Ditolak", "b-lost")})

    @app.template_filter("status_cls")
    def status_cls(v):
        return STATUS.get(v, ("", ""))[1]

    @app.template_filter("status_label")
    def status_label(v):
        return tr(STATUS.get(v, (v, ""))[0])

    @app.template_filter("status_help")
    def status_help(v):
        return tr(FEEDBACK_STATUS_HELP.get(v, ""))

    @app.template_filter("role_label")
    def role_label(v):
        return tr(ROLE_LABELS.get(v, v or "-"))

    @app.template_filter("initials")
    def initials(name):
        parts = [p for p in str(name).replace("[", "").replace("]", "").split() if p]
        return "".join(p[0] for p in parts[-2:] if p[0].isalnum()).upper()[:2] or "?"

    def team_photo(m):
        """URL foto anggota jika filenya ada di static/images/team/, selain itu '' (tampil inisial)."""
        folder = Path(app.static_folder) / "images" / "team"
        names = []
        if m.get("photo"):
            names.append(os.path.basename(str(m["photo"]).strip()))
        nim = str(m.get("nim") or "").replace("NIM", "").strip()
        names += [f"{nim}.{e}" for e in ("jpg", "jpeg", "png", "webp")] if nim.isalnum() else []
        for n in names:
            if n and (folder / n).is_file():
                return url_for("static", filename=f"images/team/{n}")
        return ""

    app.jinja_env.globals["team_photo"] = team_photo

    def brand():
        """Info logo: url (kosong jika file logo tidak ada), show_name, height. Ada ?v=<waktu ubah> agar logo baru langsung tampil."""
        folder = Path(app.static_folder) / "images"
        names = [os.path.basename(branding.LOGO_FILE.strip())] if branding.LOGO_FILE.strip() else \
            [f"logo.{e}" for e in ("svg", "png", "webp", "jpg", "jpeg")]
        for n in names:
            f = folder / n
            if n and f.is_file():
                return {"url": url_for("static", filename=f"images/{n}") + f"?v={int(f.stat().st_mtime)}",
                        "show_name": branding.SHOW_NAME, "height": int(branding.LOGO_HEIGHT)}
        return {"url": "", "show_name": True, "height": int(branding.LOGO_HEIGHT)}

    app.jinja_env.globals["brand"] = brand

    @app.context_processor
    def inject():
        from datetime import datetime
        u = g.get("user")       # mahasiswa: pembaruan Satpam belum dibaca; Satpam: balasan pengirim belum dibuka
        unread = (FB.staff_unread_count(bool(u["is_demo"])) if u["role"] == "security" else FB.unread_count(u["id"])) if u else 0
        return {"lang": get_lang(), "csrf_token": csrf_token, "team_project": team_members.PROJECT, "now_year": datetime.now().year, "unread_fb": unread}

    app.jinja_env.globals["flashes"] = lambda: [[c, tr(m)] for c, m in get_flashed_messages(with_categories=True)]
    app.jinja_env.globals["js_strings"] = js_strings
    app.jinja_env.globals["tr"] = tr

    @app.after_request
    def i18n_response(resp):
        """Bahasa EN: terjemahkan HTML hasil render dan pesan JSON. Bahasa ID: tidak diubah."""
        if get_lang() != "en" or resp.direct_passthrough:
            return resp
        if resp.mimetype == "text/html":
            resp.set_data(translate_html(resp.get_data(as_text=True)))
        elif resp.mimetype == "application/json" and (request.path == "/feedback/send" or request.path.startswith(("/satpam/feedback/", "/feedback/mine/"))):
            data = resp.get_json(silent=True)
            if isinstance(data, dict) and "message" in data:
                data["message"] = tr(data["message"])
                resp.set_data(__import__("json").dumps(data))
        return resp

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/reset-password/"):          # halaman berisi token: jangan di-cache
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def err_page(code, title, text):
        if request.path.startswith("/feedback/send") or request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=False, message=text), code
        return render_template("error.html", code=code, title=title, text=text), code

    @app.errorhandler(400)
    def e400(e): return err_page(400, "Permintaan tidak valid", getattr(e, "description", "Permintaan tidak valid."))
    @app.errorhandler(403)
    def e403(e): return err_page(403, "Akses ditolak", "Halaman ini hanya untuk Satpam.")
    @app.errorhandler(404)
    def e404(e): return err_page(404, "Halaman tidak ditemukan", "Tautan yang Anda buka tidak tersedia.")
    @app.errorhandler(413)
    def e413(e):
        return err_page(413, "File terlalu besar", "Ukuran foto maksimal 2 MB.")
    @app.errorhandler(500)
    def e500(e): return err_page(500, "Terjadi kesalahan", "Terjadi kesalahan pada server. Silakan coba lagi.")

    @app.cli.command("init-db")
    def _init():
        init_db(app); print("Database siap.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
