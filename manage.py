"""Alat administrasi. Akun Satpam hanya bisa dibuat lewat sini (atau akun awal dari .env), bukan lewat halaman Register.

  python manage.py create-security        # membuat akun Satpam baru (password diminta tanpa tampil di layar)
  python manage.py list-security          # melihat daftar akun Satpam
  python manage.py reset-demo --yes       # mengosongkan aktivitas akun demo (akun demo tetap ada, data asli tidak disentuh)
  python manage.py remove-demo --yes      # menghapus akun DEMO beserta aktivitasnya (data asli tidak disentuh)
  python manage.py test-email EMAIL       # kirim email uji Lupa Password lewat EmailJS dan tampilkan hasil/penyebab gagal
"""
import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

from app import app
from database.db import execute, query
from models import user as U
from services.security import EMAIL_RE, valid_password, valid_phone


def create_security(args):
    name = args.name or input("Nama lengkap Satpam: ").strip()
    email = (args.email or input("Email: ")).strip().lower()
    phone, err = valid_phone(args.phone or input("Nomor telepon: "))
    if len(name) < 3 or not EMAIL_RE.match(email) or err:
        sys.exit(err or "Nama atau email tidak valid.")
    pw = args.password or getpass.getpass("Password (min. 8 karakter, huruf+angka): ")
    if valid_password(pw):
        sys.exit(valid_password(pw))
    with app.app_context():
        if U.email_taken(email):
            sys.exit("Email sudah terdaftar.")
        execute("INSERT INTO users(name,email,nim,phone,password_hash,role) VALUES (?,?,NULL,?,?, 'security')",
                (name, email, phone, generate_password_hash(pw)))
    print(f"Akun Satpam dibuat: {email}")


def list_security(_):
    with app.app_context():
        for r in query("SELECT name,email,phone,created_at FROM users WHERE role='security'"):
            print(f"{r['name']} <{r['email']}> {r['phone']} (dibuat {r['created_at']})")


def test_email_cmd(args):
    """Uji nyata pengiriman EmailJS (memakai konfigurasi .env yang sedang dibaca aplikasi). Tautan di email uji TIDAK valid."""
    from services import email_service as ES
    email = args.email.strip().lower()
    if not EMAIL_RE.match(email):
        sys.exit("Alamat email tidak valid.")
    with app.app_context():
        print("== Konfigurasi yang terbaca ==")
        print("\n".join(ES.diagnose(app.config)))
        miss = ES.missing(app.config)
        if miss:
            sys.exit(f"\nBelum terisi: {', '.join(miss)}. Isi di file .env (bukan .env.example) lalu jalankan ulang perintah ini.")
        base = app.config["APP_BASE_URL"] or "http://127.0.0.1:5000"
        print(f"\n== Mengirim email uji ke {email} ==")
        status, detail = ES.send_reset_email(email, f"{base}/reset-password/CONTOH-TIDAK-VALID")
        print(f"Hasil: {status}\nRespons EmailJS: {detail}")
        if status == "sent":
            print("\nBERHASIL. Cek inbox (dan folder spam). Tautan di email uji hanyalah contoh dan tidak berlaku.")
        else:
            print(f"\nKemungkinan penyebab: {ES.hint_for(detail)}")
            sys.exit(1)


def remove_demo_cmd(args):
    if not args.yes:
        sys.exit("Ini menghapus akun dan data demo (is_demo=1). Jalankan lagi dengan --yes untuk melanjutkan.")
    import sqlite3
    from database.demo import remove_demo
    con = sqlite3.connect(app.config["DATABASE"])
    remove_demo(con, app.config["UPLOAD_FOLDER"], app.config["PRIVATE_UPLOAD_FOLDER"])
    con.close()
    print("Akun dan data demo dihapus. Set DEMO_ENABLED=0 di .env agar tidak dibuat lagi saat aplikasi dijalankan.")


def reset_demo_cmd(args):
    if not args.yes:
        sys.exit("Ini mengosongkan semua aktivitas akun demo (is_demo=1). Jalankan lagi dengan --yes untuk melanjutkan.")
    import sqlite3
    from database.demo import purge_demo_activity
    con = sqlite3.connect(app.config["DATABASE"])
    purge_demo_activity(con, app.config["UPLOAD_FOLDER"], app.config["PRIVATE_UPLOAD_FOLDER"])
    con.close()
    print("Aktivitas demo dikosongkan. Akun demo tetap ada dan data asli tidak disentuh.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-security")
    for a in ("name", "email", "phone", "password"):
        c.add_argument(f"--{a}")
    c.set_defaults(fn=create_security)
    sub.add_parser("list-security").set_defaults(fn=list_security)
    rd = sub.add_parser("reset-demo"); rd.add_argument("--yes", action="store_true"); rd.set_defaults(fn=reset_demo_cmd)
    r = sub.add_parser("remove-demo"); r.add_argument("--yes", action="store_true"); r.set_defaults(fn=remove_demo_cmd)
    te = sub.add_parser("test-email"); te.add_argument("email"); te.set_defaults(fn=test_email_cmd)
    a = ap.parse_args()
    a.fn(a)
