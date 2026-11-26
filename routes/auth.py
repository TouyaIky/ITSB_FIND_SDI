from urllib.parse import urlsplit

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import query
from models import user as U
from services import password_reset as PR
from services.email_service import is_configured, send_reset_email_async
from config.settings import USER_TYPES
from services.security import EMAIL_RE, client_ip, rate_limited, valid_password, valid_phone

bp = Blueprint("auth", __name__)
DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


def _home():
    return redirect(url_for("satpam.dashboard" if g.user and g.user["role"] == "security" else "user.dashboard"))


def _demo_info():
    """Kredensial demo tampil di halaman login hanya jika akun demo benar-benar ada di database."""
    c = current_app.config
    if not c["DEMO_ENABLED"]:
        return None
    rows = {r["email"]: r for r in query("SELECT email,role FROM users WHERE is_demo=1")}
    out = {}
    for key, email, pw, role in (("user", c["DEMO_USER_EMAIL"], c["DEMO_USER_PASSWORD"], "student"),
                                 ("security", c["DEMO_SECURITY_EMAIL"], c["DEMO_SECURITY_PASSWORD"], "security")):
        if email in rows and rows[email]["role"] == role:
            out[key] = {"email": email, "password": pw}
    return out or None


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return _home()
    form = {"user_type": "student"}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("user_type", "name", "email", "nim", "phone")}
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        allowed = {k for k, _ in USER_TYPES}          # 'security' sengaja tidak ada: Satpam tidak bisa mendaftar sendiri
        err = None
        phone, phone_err = valid_phone(form["phone"])
        is_student = form["user_type"] == "student"
        if rate_limited(f"reg:{client_ip()}", 10, 3600):
            err = "Terlalu banyak percobaan pendaftaran. Coba lagi nanti."
        elif form["user_type"] not in allowed:
            err = "Pilih jenis pengguna yang valid."
        elif not all([form["name"], form["email"], form["phone"], pw, pw2]) or (is_student and not form["nim"]):
            err = "Seluruh data wajib diisi." if not is_student else "Seluruh data wajib diisi, termasuk NIM."
        elif len(form["name"]) < 3 or len(form["name"]) > 80:
            err = "Nama lengkap harus 3–80 karakter."
        elif not EMAIL_RE.match(form["email"]):
            err = "Format email tidak valid."
        elif phone_err:
            err = phone_err
        elif is_student and (not form["nim"].isalnum() or not 5 <= len(form["nim"]) <= 20):
            err = "NIM harus 5–20 karakter huruf/angka."
        elif pw != pw2:
            err = "Password dan konfirmasi password tidak sama."
        elif valid_password(pw):
            err = valid_password(pw)
        elif U.email_taken(form["email"]):
            err = "Email sudah digunakan akun lain."
        elif is_student and U.nim_taken(form["nim"]):
            err = "NIM sudah digunakan akun lain."
        if err:
            flash(err, "error")
        else:
            U.create(form["name"], form["email"], form["nim"] if is_student else None, phone, form["user_type"],
                     generate_password_hash(pw))
            flash("Pendaftaran berhasil. Silakan masuk.", "success")
            return redirect(url_for("auth.login"))
    return render_template("register.html", form=form, user_types=USER_TYPES)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return _home()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        key = f"login:{client_ip()}:{email}"
        from services.security import peek_count
        if peek_count(key, 300) >= 5:
            flash("Terlalu banyak percobaan masuk. Coba lagi dalam beberapa menit.", "error")
            return render_template("login.html", email=email, demo=_demo_info()), 429
        user = U.by_email(email) if email else None
        ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, pw) and user is not None
        if not ok:
            rate_limited(key, 5, 300)   # hanya kegagalan yang dihitung
            flash("Email atau password salah.", "error")
            return render_template("login.html", email=email, demo=_demo_info()), 401
        session.clear()                 # cegah session fixation
        session["uid"] = user["id"]
        session.permanent = True
        flash(f"Selamat datang, {user['name'].split()[0]}!", "success")
        return redirect(url_for("satpam.dashboard" if user["role"] == "security" else "user.dashboard"))
    return render_template("login.html", email="", demo=_demo_info())


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Anda telah keluar.", "info")
    return redirect(url_for("main.landing"))


def _link_base():
    """Dasar tautan reset HARUS dari konfigurasi (APP_BASE_URL), bukan header Host yang bisa dipalsukan penyerang.
    Tanpa APP_BASE_URL, header Host hanya dipercaya jika loopback (pengembangan lokal); selain itu kembalikan '' (email tidak dikirim)."""
    base = current_app.config["APP_BASE_URL"]
    if base:
        return base
    return request.url_root.rstrip("/") if urlsplit(request.url_root).hostname in ("localhost", "127.0.0.1", "::1") else ""


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        generic = "Jika email terdaftar, instruksi reset password akan dikirim."
        if rate_limited(f"reset-ip:{client_ip()}", 5, 3600):
            flash("Terlalu banyak permintaan reset. Coba lagi dalam satu jam.", "error")
            return render_template("forgot_password.html"), 429
        if not EMAIL_RE.match(email):
            flash("Masukkan alamat email yang valid.", "error")
            return render_template("forgot_password.html"), 400
        user = U.by_email(email)
        base = _link_base()
        if user and not user["is_demo"] and PR.recent_count(user["id"]) < 3:   # akun demo tidak bisa di-reset
            if not base:
                current_app.logger.error("APP_BASE_URL belum diisi: email reset password tidak dikirim.")
            else:
                token = PR.create_token(user["id"], current_app.config["RESET_TOKEN_MINUTES"])
                link = f"{base}{url_for('auth.reset_password', token=token)}"
                if is_configured():
                    send_reset_email_async(user["email"], link)         # latar belakang: waktu respons tidak membocorkan keberadaan akun
                else:
                    current_app.logger.warning("EmailJS belum dikonfigurasi: email reset tidak dikirim.")
                    if current_app.debug:
                        print(f"\n[DEV] Link reset untuk {user['email']}: {link}\n")   # HANYA mode pengembangan
        flash(generic, "info")            # pesan sama untuk email terdaftar maupun tidak
        return redirect(url_for("auth.forgot_password"))
    return render_template("forgot_password.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = PR.find_valid(token)
    if not row:
        flash("Tautan reset tidak valid atau sudah kedaluwarsa. Silakan minta tautan baru.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        err = ("Password dan konfirmasi password tidak sama." if pw != pw2 else valid_password(pw))
        if err:
            flash(err, "error")
            return render_template("reset_password.html", token=token), 400
        if not PR.consume(row["id"]):         # atomik: token yang sama tidak bisa dipakai dua kali, juga saat permintaan serentak
            flash("Tautan reset tidak valid atau sudah kedaluwarsa. Silakan minta tautan baru.", "error")
            return redirect(url_for("auth.forgot_password"))
        U.set_password(row["user_id"], generate_password_hash(pw))
        PR.invalidate_user(row["user_id"])
        flash("Password berhasil diperbarui. Silakan masuk.", "success")
        return redirect(url_for("auth.login"))
    return render_template("reset_password.html", token=token)
