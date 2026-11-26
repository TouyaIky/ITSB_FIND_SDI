import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _flag(name, default="0"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    DEBUG = _flag("FLASK_DEBUG", "1")
    DATABASE = str(BASE_DIR / "database" / "itsb_find.db")
    UPLOAD_FOLDER = str(BASE_DIR / "static" / "uploads")
    MAX_CONTENT_LENGTH = 3 * 1024 * 1024          # batas keras request (3 MB)
    MAX_IMAGE_BYTES = 2 * 1024 * 1024             # batas foto (2 MB)
    ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png"}
    APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")
    PRIVATE_UPLOAD_FOLDER = str(BASE_DIR / "instance" / "private_uploads")   # foto dokumentasi: TIDAK publik
    # Akun Satpam awal (dibuat otomatis jika belum ada akun Satpam). Ganti di .env!
    # Nama variabel lama ADMIN_* tetap didukung agar .env lama tidak rusak.
    SECURITY_NAME = os.getenv("SECURITY_NAME", os.getenv("ADMIN_NAME", "Satpam ITSB"))
    SECURITY_EMAIL = os.getenv("SECURITY_EMAIL", os.getenv("ADMIN_EMAIL", "satpam@itsb.test"))
    SECURITY_PHONE = os.getenv("SECURITY_PHONE", "081200000000")
    SECURITY_PASSWORD = os.getenv("SECURITY_PASSWORD", os.getenv("ADMIN_PASSWORD", "Satpam12345"))

    # Akun & data demonstrasi untuk pengujian dosen. Kredensial demo bersifat publik (tampil di halaman login),
    # jadi bukan rahasia; ganti lewat .env bila perlu. DEMO_ENABLED=0 mematikan pembuatan akun demo. Akun demo selalu bersih: tidak ada data contoh.
    DEMO_ENABLED = _flag("DEMO_ENABLED", "1")
    DEMO_USER_EMAIL = os.getenv("DEMO_USER_EMAIL", "demo.user@itsb.test").strip().lower()
    DEMO_USER_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "DemoUser2026")
    DEMO_SECURITY_EMAIL = os.getenv("DEMO_SECURITY_EMAIL", "demo.satpam@itsb.test").strip().lower()
    DEMO_SECURITY_PASSWORD = os.getenv("DEMO_SECURITY_PASSWORD", "DemoSatpam2026")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE", "0")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8      # 8 jam

    RESET_TOKEN_MINUTES = 60                       # tautan reset berlaku 1 jam, sekali pakai

    EMAILJS_SERVICE_ID = os.getenv("EMAILJS_SERVICE_ID", "service_qi5y932")
    EMAILJS_PUBLIC_KEY = os.getenv("EMAILJS_PUBLIC_KEY", "z7XS06a3XBvihz-h5")
    EMAILJS_PRIVATE_KEY = os.getenv("EMAILJS_PRIVATE_KEY", "")
    # Nama lama EMAILJS_RESET_TEMPLATE_ID tetap dibaca sebagai cadangan agar .env lama tidak rusak.
    EMAILJS_TEMPLATE_ID = os.getenv("EMAILJS_TEMPLATE_ID") or os.getenv("EMAILJS_RESET_TEMPLATE_ID", "template_mzsv7pa")
    EMAILJS_API_URL = os.getenv("EMAILJS_API_URL", "https://api.emailjs.com/api/v1.0/email/send")


CATEGORIES = [
    "Elektronik", "Dompet & Dokumen", "Kartu (KTM/ATM)", "Tas", "Kunci",
    "Pakaian & Aksesori", "Alat Tulis & Buku", "Botol & Peralatan Makan", "Lainnya",
]
LOCATION_SUGGESTIONS = [
    "Perpustakaan", "Kantin", "Masjid / Musala", "Parkiran", "Laboratorium",
    "Ruang Kelas", "Lobi", "Toilet", "Lapangan", "Taman Kampus",
]
USER_TYPES = [("student", "Mahasiswa"), ("lecturer", "Dosen"), ("guest", "Tamu"), ("staff", "Staff ITSB")]
ROLE_LABELS = dict(USER_TYPES, security="Satpam")
FEEDBACK_STATUSES = [  # (kode, label ID, kelas badge)
    ("new", "Menunggu Ditinjau", "b-info"), ("reviewing", "Sedang Ditinjau", "b-pending"), ("in_progress", "Sedang Ditindaklanjuti", "b-prog"),
    ("done", "Selesai", "b-stored"), ("rejected", "Tidak Dapat Ditindaklanjuti", "b-lost")]
FEEDBACK_CATEGORIES = ["Kritik", "Saran", "Bug atau kendala", "Masukan fitur", "Lainnya"]
FEEDBACK_STATUS_HELP = {  # penjelasan singkat untuk pengirim
    "new": "Masukanmu sudah diterima dan menunggu giliran dibaca oleh Satpam.",
    "reviewing": "Satpam sedang membaca dan menilai masukanmu.",
    "in_progress": "Masukanmu diterima dan sedang dikerjakan atau diteruskan ke pihak terkait.",
    "done": "Masukanmu sudah selesai ditangani.",
    "rejected": "Masukanmu belum dapat ditindaklanjuti. Alasannya dijelaskan oleh Satpam."}
FEEDBACK_REPLY_TEMPLATES = [  # (label singkat, isi) untuk balasan cepat Satpam
    ("Terima kasih", "Terima kasih atas masukannya. Masukan Anda sudah kami terima dan akan kami tinjau."),
    ("Sedang dicek", "Masukan Anda sedang kami periksa bersama pihak terkait. Kami kabari kembali setelah ada perkembangan."),
    ("Sudah ditindaklanjuti", "Masukan Anda sudah kami tindaklanjuti. Terima kasih sudah membantu kami memperbaiki layanan."),
    ("Butuh info tambahan", "Agar dapat kami tindaklanjuti, mohon kirim masukan baru dengan informasi lebih rinci (lokasi, waktu, atau kejadian)."),
]


def production_warnings(cfg):
    """Daftar peringatan konfigurasi yang tidak aman untuk dipakai sungguhan (dipanggil saat startup; hanya log, tidak menghentikan aplikasi)."""
    if cfg.get("DEBUG") or cfg.get("TESTING"):
        return []
    w = []
    if cfg.get("SECRET_KEY") in ("", "dev-only-change-me", "ganti-dengan-string-acak-panjang"):
        w.append("SECRET_KEY masih bawaan: sesi/CSRF bisa dipalsukan. Isi string acak panjang di .env.")
    if not cfg.get("SESSION_COOKIE_SECURE"):
        w.append("SESSION_COOKIE_SECURE=0: cookie sesi bisa terkirim lewat HTTP. Set 1 bila sudah memakai HTTPS.")
    if cfg.get("SECURITY_PASSWORD") == "Satpam12345":
        w.append("SECURITY_PASSWORD masih bawaan: ganti password akun Satpam utama.")
    base = cfg.get("APP_BASE_URL") or ""
    if not base:
        w.append("APP_BASE_URL kosong: email reset password TIDAK dikirim (mencegah tautan palsu lewat header Host). Isi URL deployment, mis. https://USERNAME.pythonanywhere.com")
    elif "localhost" in base or "127.0.0.1" in base:
        w.append("APP_BASE_URL masih localhost: tautan reset di email tidak akan bisa dibuka dari luar. Isi URL deployment.")
    elif base.startswith("http://"):
        w.append("APP_BASE_URL memakai http://: gunakan https:// agar token reset tidak terkirim tanpa enkripsi.")
    if not all(cfg.get(k) and not str(cfg.get(k)).startswith("YOUR_") for k in ("EMAILJS_SERVICE_ID", "EMAILJS_TEMPLATE_ID", "EMAILJS_PUBLIC_KEY")):
        w.append("EMAILJS_SERVICE_ID / EMAILJS_TEMPLATE_ID / EMAILJS_PUBLIC_KEY belum lengkap: email lupa password tidak akan terkirim.")
    if cfg.get("DEMO_ENABLED"):
        w.append("DEMO_ENABLED=1: kredensial akun demo tampil publik di halaman login. Set 0 untuk penggunaan sungguhan.")
    return w
