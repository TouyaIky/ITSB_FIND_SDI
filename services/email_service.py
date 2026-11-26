"""Pengiriman email reset password lewat EmailJS REST API dari BACKEND Flask.

EmailJS HANYA dipakai untuk Lupa Password (kritik dan saran tidak memakai email).
Konfigurasi dari environment: EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY
(opsional: EMAILJS_PRIVATE_KEY bila di dashboard EmailJS opsi "Use Private Key" aktif).

Prasyarat di dashboard EmailJS: Account > Security > aktifkan
"Allow EmailJS API for non-browser applications", karena pemanggilan dilakukan dari server.

Template EmailJS memakai tepat dua variabel: {{to_email}} (penerima) dan {{link}} (tautan reset).
Password lama/baru tidak pernah dikirim lewat email; token mentah hanya ada di dalam tautan."""
import json
import threading
import urllib.error
import urllib.request

from flask import current_app

API_URL = "https://api.emailjs.com/api/v1.0/email/send"


def _set(v):
    return bool(v) and not str(v).startswith("YOUR_")


def is_configured():
    c = current_app.config
    return _set(c["EMAILJS_SERVICE_ID"]) and _set(c["EMAILJS_TEMPLATE_ID"]) and _set(c["EMAILJS_PUBLIC_KEY"])


REQUIRED = ("EMAILJS_SERVICE_ID", "EMAILJS_TEMPLATE_ID", "EMAILJS_PUBLIC_KEY")


def missing(cfg):
    """Nama variabel EmailJS yang belum terisi (kosong atau masih placeholder YOUR_...)."""
    return [k for k in REQUIRED if not _set(cfg.get(k))]


def env_file_status():
    """(path, ada?) untuk file .env yang dibaca aplikasi. Nilai di .env.example TIDAK dibaca."""
    from config.settings import BASE_DIR
    p = BASE_DIR / ".env"
    return str(p), p.is_file()


def diagnose(cfg):
    """Ringkasan konfigurasi EmailJS yang aman ditampilkan (rahasia disamarkan, tidak pernah dicetak utuh)."""
    def mask(v):
        v = str(v or "")
        return "(kosong)" if not v else (v[:4] + "…" + f" ({len(v)} karakter)")
    path, found = env_file_status()
    lines = [f"File .env: {'ditemukan' if found else 'TIDAK ditemukan'} di {path}"]
    if not found:
        lines.append("  -> Nilai yang diisi di .env.example tidak dibaca aplikasi. Salin/ganti nama menjadi .env, lalu restart server.")
    for k in REQUIRED + ("EMAILJS_PRIVATE_KEY",):
        v = cfg.get(k)
        lines.append(f"{k}: {'terisi ' + mask(v) if _set(v) else ('KOSONG' if k in REQUIRED else 'tidak diisi (opsional)')}")
    lines.append(f"APP_BASE_URL: {cfg.get('APP_BASE_URL') or '(kosong)'}")
    return lines


def hint_for(detail):
    """Tebakan penyebab dari pesan galat EmailJS/jaringan (berdasarkan kata kunci), untuk membantu diagnosis."""
    d = (detail or "").lower()
    if not d.startswith("http"):            # bukan jawaban EmailJS (DNS, timeout, koneksi ditolak, dll.)
        return "Gagal terhubung ke api.emailjs.com (internet/firewall/proxy?). Pastikan koneksi keluar diizinkan."
    if "non-browser" in d:
        return "Aktifkan Account > Security > 'Allow EmailJS API for non-browser applications' di dashboard EmailJS."
    if "public key" in d or "user_id" in d or "user id" in d:
        return "Public Key ditolak. Salin ulang dari Account > General (tanpa spasi)."
    if "template" in d:
        return "Template ID tidak ditemukan/tidak cocok dengan akun ini. Periksa EMAILJS_TEMPLATE_ID."
    if "service" in d:
        return "Service ID tidak ditemukan/belum terhubung. Periksa EMAILJS_SERVICE_ID dan status layanan email di EmailJS."
    if "private" in d or "access token" in d or "accesstoken" in d:
        return "Private Key ditolak atau diperlukan. Buat ulang di Account > API keys, atau kosongkan EMAILJS_PRIVATE_KEY bila 'Use Private Key' tidak aktif."
    if "limit" in d or "quota" in d:
        return "Kuota EmailJS habis atau terkena batas laju. Coba lagi nanti atau cek paket akun."
    if "http 4" in d or "http 5" in d:
        return "EmailJS menolak permintaan. Baca pesan di atas untuk alasan pastinya."
    return "Gagal terhubung ke api.emailjs.com (internet/firewall/proxy?). Pastikan koneksi keluar diizinkan."


def send_reset_email(to_email, link):
    """Kirim email reset. Return (status, detail): status in sent | failed | not_configured."""
    if not is_configured():
        return "not_configured", "EmailJS belum dikonfigurasi."
    c = current_app.config
    payload = {
        "service_id": c["EMAILJS_SERVICE_ID"],
        "template_id": c["EMAILJS_TEMPLATE_ID"],
        "user_id": c["EMAILJS_PUBLIC_KEY"],
        "template_params": {"to_email": to_email, "link": link},
    }
    if _set(c.get("EMAILJS_PRIVATE_KEY")):
        payload["accessToken"] = c["EMAILJS_PRIVATE_KEY"]
    req = urllib.request.Request(c.get("EMAILJS_API_URL") or API_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "ITSB-Find/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read().decode(errors="ignore")
            return ("sent", body) if r.status == 200 else ("failed", f"HTTP {r.status}: {body[:200]}")
    except urllib.error.HTTPError as e:
        return "failed", f"HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}"
    except Exception as e:  # jaringan, timeout, dll.
        return "failed", str(e)


def send_reset_email_async(to_email, link):
    """Kirim di latar belakang agar waktu respons sama untuk email terdaftar maupun tidak (tidak bisa ditebak dari kecepatan).
    Saat TESTING dijalankan langsung supaya tes deterministik. Kegagalan hanya dicatat di log (tanpa tautan/token)."""
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            status, detail = send_reset_email(to_email, link)
            if status != "sent":
                app.logger.warning("Email reset password tidak terkirim (%s): %s", status, detail)
    if app.config.get("TESTING"):
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
