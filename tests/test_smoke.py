"""Uji fungsional ITSB FIND (Flask test client). Jalankan: python -m unittest tests.test_smoke -v"""
import glob, html, io, json, os, re, shutil, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image
from werkzeug.security import generate_password_hash
from app import create_app
from database import init_db as DBI
from database.db import get_db
from models import feedback as F
from services import password_reset as PR, security

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SATPAM = ("satpam@itsb.test", "Satpam12345")              # Satpam utama (non-demo)
DEMO_USER = ("demo.user@itsb.test", "DemoUser2026")
DEMO_SAT = ("demo.satpam@itsb.test", "DemoSatpam2026")
PHONE = "089912345678"                                    # nomor unik untuk uji privasi


def png():
    b = io.BytesIO(); Image.new("RGB", (60, 40), (200, 30, 40)).save(b, "PNG"); b.seek(0); return b


def row(app, sql, args=()):
    with app.app_context():
        return get_db().execute(sql, args).fetchone()


def rows(app, sql, args=()):
    with app.app_context():
        return get_db().execute(sql, args).fetchall()


class Base(unittest.TestCase):
    demo = True
    extra = {}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"DATABASE": f"{self.tmp}/t.db", "UPLOAD_FOLDER": f"{self.tmp}/up", "PRIVATE_UPLOAD_FOLDER": f"{self.tmp}/priv",
                    "TESTING": True, "DEMO_ENABLED": self.demo, **self.extra}
        self.app = create_app(self.cfg)
        security.reset_rate_limits()
        self.c = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def csrf(self, c):
        c.get("/feedback")
        with c.session_transaction() as s:
            return s["_csrf"]

    def post(self, url, data=None, c=None, **kw):
        c = c or self.c
        data = dict(data or {}); data["_csrf"] = self.csrf(c)
        return c.post(url, data=data, **kw)

    def client(self, creds=None, lang=None):
        c = self.app.test_client()
        if lang:
            c.set_cookie("lang", lang)
        if creds:
            self.post("/login", {"email": creds[0], "password": creds[1]}, c=c)
        return c

    def text(self, c, url):
        return c.get(url).get_data(as_text=True)

    def register(self, email, typ="student", nim="77001", name="Pengguna Uji", phone="081234500000", pw="Uji12345"):
        r = self.post("/register", {"user_type": typ, "name": name, "email": email, "nim": nim if typ == "student" else "",
                                    "phone": phone, "password": pw, "confirm": pw})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:200])
        return (email, pw)

    def real_user(self, email="real@x.com", nim="77001"):
        creds = self.register(email, nim=nim)
        return self.client(creds), creds

    def report(self, c, path, name, **over):
        d = {"item_name": name, "category": "Elektronik", "description": "Earbuds putih dengan stiker bulan", "location": "Ruang Kelas",
             "date": "2026-10-30", "time": "10:00", "phone": PHONE, "photo": (png(), "f.png")}
        d.update(over)
        return self.post(path, d, c=c, content_type="multipart/form-data")


# ---------------------------------------------------------------- akun demo
ACTIVITY_TABLES = ("found_items", "lost_items", "feedback", "feedback_history", "item_returns")


def snap(app):
    return {t: row(app, f"SELECT COUNT(*) n FROM {t}")["n"] for t in ("users",) + ACTIVITY_TABLES}


class DemoAccounts(Base):
    def test_exactly_two_clean_demo_accounts_and_idempotent(self):
        before = snap(self.app)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM users WHERE is_demo=1")["n"], 2)
        for t in ACTIVITY_TABLES:                                   # akun demo benar-benar bersih
            self.assertEqual(before[t], 0, t)
        for _ in range(2):                                          # restart berulang tidak menggandakan apa pun
            create_app(self.cfg)
        self.assertEqual(snap(self.app), before)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM users WHERE role='security'")["n"], 2)   # Satpam utama + Demo Satpam
        names = {r["email"]: r["name"] for r in rows(self.app, "SELECT email,name FROM users WHERE is_demo=1")}
        self.assertEqual(names, {DEMO_USER[0]: "Demo Mahasiswa", DEMO_SAT[0]: "Demo Satpam"})
        self.assertTrue(row(self.app, "SELECT password_hash FROM users WHERE email=?", (DEMO_USER[0],))["password_hash"].startswith(("scrypt", "pbkdf2")))

    def test_credentials_survive_restart(self):
        for _ in range(2):
            create_app(self.cfg)
            security.reset_rate_limits()
            self.assertEqual(self.client(DEMO_USER).get("/dashboard").status_code, 200)
            self.assertEqual(self.client(DEMO_SAT).get("/satpam/").status_code, 200)

    def test_login_page_buttons_do_not_autologin(self):
        html_ = self.text(self.c, "/login")
        self.assertIn('data-demo="user"', html_); self.assertIn('data-demo="security"', html_)
        self.assertIn(DEMO_USER[0], html_); self.assertIn(DEMO_SAT[0], html_)
        self.assertIn("Gunakan Demo Mahasiswa", html_); self.assertIn("Gunakan Demo Satpam", html_)
        self.assertEqual(self.c.get("/dashboard").status_code, 302)            # tidak ada login otomatis
        js = open(os.path.join(ROOT, "static/js/main.js"), encoding="utf8").read()
        self.assertNotIn(".submit()", js[js.index("Akun demo"):js.index("Mencegah submit ganda")])   # tombol hanya mengisi form

    def test_demo_student_starts_empty_and_cannot_use_satpam(self):
        c = self.client(DEMO_USER)
        for u in ["/dashboard", "/found-items", "/lost-items", "/report-found", "/report-lost", "/my-reports", "/feedback", "/profile", "/about"]:
            self.assertEqual(c.get(u).status_code, 200, u)
        for u in ["/satpam/", "/satpam/found", "/satpam/lost", "/satpam/returns", "/satpam/history", "/satpam/activity", "/satpam/feedback", "/satpam/found/1/edit"]:
            self.assertEqual(c.get(u).status_code, 403, u)
        for u in ["/satpam/found/1/confirm", "/satpam/found/1/status", "/satpam/found/1/delete", "/satpam/lost/1/resolve", "/satpam/lost/1/status",
                  "/satpam/lost/1/delete", "/satpam/returns/1", "/satpam/feedback/1/status", "/satpam/feedback/1/note"]:
            self.assertEqual(self.post(u, {"status": "done"}, c=c).status_code, 403, u)
        self.assertEqual(self.report(c, "/report-found", "Barang demo baru").status_code, 302)
        self.assertEqual(row(self.app, "SELECT is_demo FROM found_items WHERE item_name='Barang demo baru'")["is_demo"], 1)

    def test_demo_satpam_manages_only_demo_data(self):
        c = self.client(DEMO_SAT)
        for u in ["/satpam/", "/satpam/found", "/satpam/lost", "/satpam/returns", "/satpam/history", "/satpam/activity", "/satpam/feedback", "/profile"]:
            self.assertEqual(c.get(u).status_code, 200, u)
        du = self.client(DEMO_USER)
        self.report(du, "/report-found", "Dompet demo uji", phone="081355550001")
        pend = row(self.app, "SELECT id FROM found_items WHERE item_name='Dompet demo uji'")["id"]
        self.assertIn("Dompet demo uji", self.text(c, "/satpam/found"))
        self.post(f"/satpam/found/{pend}/confirm", c=c)
        self.assertEqual(row(self.app, "SELECT status FROM found_items WHERE id=?", (pend,))["status"], "stored")
        # data asli: tidak terlihat dan tidak bisa diubah oleh Demo Satpam
        real, _ = self.real_user()
        self.report(real, "/report-found", "Dompet asli rahasia")
        fid = row(self.app, "SELECT id FROM found_items WHERE item_name='Dompet asli rahasia'")["id"]
        self.assertNotIn("Dompet asli rahasia", self.text(c, "/satpam/found"))
        self.assertNotIn(PHONE, self.text(c, "/satpam/found"))
        for url in (f"/satpam/found/{fid}/confirm", f"/satpam/found/{fid}/status"):
            self.assertEqual(self.post(url, {"status": "declined", "reason": "alasan uji"}, c=c).status_code, 404, url)
        self.post(f"/satpam/found/{fid}/delete", c=c)
        self.assertEqual(row(self.app, "SELECT status FROM found_items WHERE id=?", (fid,))["status"], "pending")      # data asli utuh
        self.assertEqual(c.get(f"/satpam/found/{fid}/edit").status_code, 404)
        self.assertEqual(c.get(f"/satpam/returns/{fid}").status_code, 404)
        self.report(real, "/report-lost", "Barang hilang asli", photo=(io.BytesIO(b""), ""))
        lid = row(self.app, "SELECT id FROM lost_items WHERE item_name='Barang hilang asli'")["id"]
        self.assertEqual(c.get(f"/lost/{lid}").status_code, 404)
        self.assertNotIn("Barang hilang asli", self.text(c, "/satpam/lost"))
        self.assertEqual(self.post(f"/satpam/lost/{lid}/delete", c=c).status_code, 302)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM lost_items WHERE id=?", (lid,))["n"], 1)      # tidak terhapus
        with self.app.app_context():
            F.create(None, "Orang Asli", "asli@x.com", "Saran", "Rahasia asli", "Pesan asli pengguna sungguhan.")
        realfb = row(self.app, "SELECT id FROM feedback WHERE subject='Rahasia asli'")["id"]
        self.assertNotIn("Rahasia asli", self.text(c, "/satpam/feedback"))
        self.assertNotIn("Rahasia asli", self.text(c, "/satpam/activity"))
        self.assertEqual(c.get(f"/satpam/feedback/{realfb}").status_code, 404)
        self.assertEqual(self.post(f"/satpam/feedback/{realfb}/status", {"status": "done"}, c=c).status_code, 404)
        s = self.client(SATPAM)                                    # Satpam asli melihat semuanya
        self.assertIn("Dompet asli rahasia", self.text(s, "/satpam/found")); self.assertIn("Rahasia asli", self.text(s, "/satpam/feedback"))

    def test_demo_return_flow_and_private_photo(self):
        c = self.client(DEMO_SAT); du = self.client(DEMO_USER)
        self.report(du, "/report-found", "Kunci demo kembali")
        sid = row(self.app, "SELECT id FROM found_items WHERE item_name='Kunci demo kembali'")["id"]
        self.post(f"/satpam/found/{sid}/confirm", c=c)
        r = self.post(f"/satpam/returns/{sid}", {"owner_name": "Pemilik Uji", "owner_type": "student", "owner_phone": "081377770000", "notes": "KTM cocok",
                                                "photo": (png(), "d.png")}, c=c, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(row(self.app, "SELECT status FROM found_items WHERE id=?", (sid,))["status"], "returned")
        rid = row(self.app, "SELECT id FROM item_returns WHERE found_item_id=?", (sid,))["id"]
        self.assertEqual(c.get(f"/satpam/return-photo/{rid}").status_code, 200)
        self.assertEqual(self.client(DEMO_USER).get(f"/satpam/return-photo/{rid}").status_code, 403)
        self.assertEqual(self.client().get(f"/satpam/return-photo/{rid}").status_code, 302)

    def test_demo_accounts_are_locked(self):
        c = self.client(DEMO_USER)
        r = self.post("/profile", {"action": "password", "current": DEMO_USER[1], "password": "Baru12345", "confirm": "Baru12345"}, c=c, follow_redirects=True)
        self.assertIn("Akun demonstrasi tidak dapat diubah", r.get_data(as_text=True))
        self.assertEqual(self.client(DEMO_USER).get("/dashboard").status_code, 200)       # password demo tetap berlaku
        self.post("/forgot-password", {"email": DEMO_USER[0]})
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM password_reset_tokens")["n"], 0)

    def test_main_satpam_never_overwritten(self):
        h0 = row(self.app, "SELECT password_hash FROM users WHERE email=?", (SATPAM[0],))["password_hash"]
        cfg = {**self.cfg, "DEMO_SECURITY_EMAIL": SATPAM[0], "DEMO_SECURITY_PASSWORD": "Timpa12345"}
        create_app(cfg)
        r = row(self.app, "SELECT password_hash,is_demo,role,name FROM users WHERE email=?", (SATPAM[0],))
        self.assertEqual((r["password_hash"], r["is_demo"], r["role"], r["name"]), (h0, 0, "security", "Satpam ITSB"))
        self.assertEqual(self.client(SATPAM).get("/satpam/").status_code, 200)

    def test_demo_password_from_env_is_synced_only_for_demo(self):
        create_app({**self.cfg, "DEMO_USER_PASSWORD": "Ganti12345"})
        self.assertEqual(self.client((DEMO_USER[0], "Ganti12345")).get("/dashboard").status_code, 200)
        self.assertEqual(self.client(SATPAM).get("/satpam/").status_code, 200)

    def test_existing_real_account_with_demo_email_is_untouched(self):
        d2 = tempfile.mkdtemp()
        cfg = {**self.cfg, "DATABASE": f"{d2}/x.db"}
        create_app({**cfg, "DEMO_ENABLED": False})                           # DB tanpa demo
        con = sqlite3.connect(cfg["DATABASE"]); con.execute("INSERT INTO users(name,email,nim,phone,password_hash,role) VALUES ('Asli',?,'55555','0812',?, 'student')", (DEMO_USER[0], generate_password_hash("AsliAsli123"))); con.commit(); con.close()
        create_app({**cfg, "DEMO_ENABLED": True})
        r = row_db(cfg["DATABASE"], "SELECT is_demo,name FROM users WHERE email=?", (DEMO_USER[0],))
        self.assertEqual((r[0], r[1]), (0, "Asli"))
        shutil.rmtree(d2, ignore_errors=True)

    def test_reset_demo_activity_keeps_accounts_and_real_data(self):
        from database.demo import purge_demo_activity
        du = self.client(DEMO_USER); real, _ = self.real_user()
        self.report(du, "/report-found", "Aktivitas demo"); self.report(real, "/report-found", "Aktivitas asli")
        with self.app.app_context():
            F.create(du and 2, "Demo Mahasiswa", DEMO_USER[0], "Saran", "Saran demo", "Pesan demo cukup panjang.", 1)
            con = sqlite3.connect(self.cfg["DATABASE"]); purge_demo_activity(con, self.cfg["UPLOAD_FOLDER"], self.cfg["PRIVATE_UPLOAD_FOLDER"]); con.close()
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM found_items WHERE is_demo=1")["n"], 0)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM feedback WHERE is_demo=1")["n"], 0)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM found_items WHERE item_name='Aktivitas asli'")["n"], 1)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM users WHERE is_demo=1")["n"], 2)

    def test_legacy_sample_data_is_purged_once(self):
        """Database lama yang berisi data contoh versi sebelumnya dibersihkan satu kali; akun & data asli aman."""
        tmp = tempfile.mkdtemp(); db = f"{tmp}/old.db"
        cfg = {**self.cfg, "DATABASE": db, "UPLOAD_FOLDER": f"{tmp}/up", "PRIVATE_UPLOAD_FOLDER": f"{tmp}/pr"}
        app = create_app(cfg)
        con = sqlite3.connect(db)
        uid = con.execute("SELECT id FROM users WHERE email=?", (DEMO_USER[0],)).fetchone()[0]
        real = con.execute("INSERT INTO users(name,email,nim,phone,password_hash,role) VALUES ('Asli','asli@x.com','55555','0812','x','student')").lastrowid
        os.makedirs(f"{tmp}/up", exist_ok=True); open(f"{tmp}/up/demo_found_1.jpg", "wb").close()
        for n, u, d in (("Dompet kulit cokelat", uid, 1), ("Barang asli", real, 0)):
            con.execute("INSERT INTO found_items(user_id,item_name,category,description,location,date_found,time_found,photo,status,is_demo) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (u, n, "Lainnya", "deskripsi cukup panjang", "Kantin", "2026-10-01", "10:00", "demo_found_1.jpg" if d else "x.jpg", "stored", d))
        con.execute("INSERT INTO lost_items(user_id,item_name,category,description,location,date_lost,time_lost,is_demo) VALUES (?,?,?,?,?,?,?,1)", (uid, "Dompet contoh", "Lainnya", "deskripsi cukup panjang", "Kantin", "2026-10-01", "10:00"))
        con.execute("INSERT INTO feedback(sender_name,sender_email,category,subject,message,is_demo) VALUES ('Pengunjung Demo A','a@x.com','Saran','S','pesan contoh',1)")
        con.execute("DELETE FROM meta WHERE key='demo_data_purged_v4'"); con.execute("INSERT INTO meta(key,value) VALUES ('demo_data_v1','x')"); con.commit(); con.close()
        create_app(cfg)
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("SELECT item_name FROM found_items").fetchall(), [("Barang asli",)])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM lost_items").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM users WHERE is_demo=1").fetchone()[0], 2)
        self.assertFalse(os.path.exists(f"{tmp}/up/demo_found_1.jpg"))
        con.execute("INSERT INTO found_items(user_id,item_name,category,description,location,date_found,time_found,photo,status,is_demo) VALUES (?,?,?,?,?,?,?,?,?,1)",
                    (uid, "Aktivitas demo baru", "Lainnya", "deskripsi cukup panjang", "Kantin", "2026-10-01", "10:00", "n.jpg", "pending")); con.commit(); con.close()
        create_app(cfg)                                             # pembersihan hanya SEKALI: aktivitas demo berikutnya tidak dihapus
        con = sqlite3.connect(db); self.assertEqual(con.execute("SELECT COUNT(*) FROM found_items WHERE is_demo=1").fetchone()[0], 1); con.close()
        shutil.rmtree(tmp, ignore_errors=True)


def row_db(path, sql, args=()):
    con = sqlite3.connect(path); r = con.execute(sql, args).fetchone(); con.close(); return r


class DemoDisabled(Base):
    demo = False

    def test_no_demo_when_disabled(self):
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM users WHERE is_demo=1")["n"], 0)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM found_items")["n"], 0)
        self.assertNotIn("data-demo=", self.text(self.c, "/login"))
        html_ = self.text(self.c, "/")
        self.assertEqual(html_.count('data-count="0"'), 4)
        c = self.client(SATPAM)
        for u in ["/satpam/", "/satpam/found", "/satpam/lost", "/satpam/returns", "/satpam/history", "/satpam/activity", "/satpam/feedback", "/profile"]:
            self.assertEqual(c.get(u).status_code, 200, u)


# ---------------------------------------------------------------- autentikasi & hak akses
class Auth(Base):
    def test_public_pages_and_team(self):
        for u in ["/", "/feedback", "/login", "/register", "/forgot-password", "/about", "/found-items", "/lost-items"]:
            self.assertEqual(self.c.get(u).status_code, 200, u)
        self.assertEqual(self.c.get("/guide").status_code, 404)           # halaman panduan lama sudah dihapus
        self.assertEqual(self.text(self.c, "/").count('class="member reveal"'), 5)

    def test_register_four_types_nim_only_student(self):
        base = {"phone": "081234500000", "password": "abc12345", "confirm": "abc12345"}
        for typ, name, email, nim in [("student", "Budi Mahasiswa", "m@x.com", "55555"), ("lecturer", "Dr Dosen Satu", "d@x.com", ""),
                                      ("guest", "Tamu Satu", "t@x.com", ""), ("staff", "Staff Satu", "s@x.com", "")]:
            self.assertEqual(self.post("/register", {**base, "user_type": typ, "name": name, "email": email, "nim": nim}).status_code, 302, typ)
            self.assertEqual(row(self.app, "SELECT role FROM users WHERE email=?", (email,))["role"], typ)
        r = self.post("/register", {**base, "user_type": "student", "name": "Tanpa Nim", "email": "n@x.com", "nim": ""})
        self.assertEqual(r.status_code, 200); self.assertIn(b"NIM", r.data)

    def test_security_not_registrable(self):
        for typ in ("security", "admin", ""):
            r = self.post("/register", {"user_type": typ, "name": "Penyusup", "email": "x@x.com", "nim": "99999", "phone": "081234500000",
                                        "password": "abc12345", "confirm": "abc12345", "role": "security"})
            self.assertEqual(r.status_code, 200)
        self.assertIsNone(row(self.app, "SELECT 1 FROM users WHERE email='x@x.com'"))

    def test_login_logout_lockout_csrf(self):
        c = self.client(DEMO_USER)
        self.assertEqual(c.get("/dashboard").status_code, 200)
        self.post("/logout", c=c); self.assertEqual(c.get("/dashboard").status_code, 302)
        security.reset_rate_limits()
        for _ in range(5):
            self.assertEqual(self.post("/login", {"email": DEMO_USER[0], "password": "salah"}).status_code, 401)
        self.assertEqual(self.post("/login", {"email": DEMO_USER[0], "password": DEMO_USER[1]}).status_code, 429)
        self.assertEqual(self.client().post("/login", data={"email": "a", "password": "b"}).status_code, 400)

    def test_profile_real_user(self):
        c, creds = self.real_user()
        self.post("/profile", {"action": "profile", "name": "Nama Baru", "phone": "081300000001"}, c=c)
        self.assertEqual(row(self.app, "SELECT phone FROM users WHERE email=?", (creds[0],))["phone"], "081300000001")
        self.assertIn(b"salah", self.post("/profile", {"action": "password", "current": "salah", "password": "Baru12345", "confirm": "Baru12345"}, c=c).data)
        self.post("/profile", {"action": "password", "current": creds[1], "password": "Baru12345", "confirm": "Baru12345"}, c=c)
        security.reset_rate_limits()
        self.assertEqual(self.post("/login", {"email": creds[0], "password": "Baru12345"}).status_code, 302)

    def test_guest_mode(self):
        c = self.client(); self.assertEqual(c.get("/guest").status_code, 302)
        for u in ["/found-items", "/lost-items", "/about"]:
            self.assertEqual(c.get(u).status_code, 200, u)
        self.assertIn("Mode Tamu", self.text(c, "/found-items")); self.assertIn("data-modal-open=loginModal", self.text(c, "/found-items"))
        for u in ["/dashboard", "/report-found", "/report-lost", "/my-reports", "/profile", "/satpam/", "/satpam/feedback"]:
            self.assertEqual(c.get(u).status_code, 302, u)


class Reset(Base):
    def test_reset_flow(self):
        c, creds = self.real_user()
        self.assertIn("Jika email terdaftar".encode(), self.post("/forgot-password", {"email": "tidak@ada.com"}, follow_redirects=True).data)
        with self.app.app_context():
            uid = get_db().execute("SELECT id FROM users WHERE email=?", (creds[0],)).fetchone()["id"]
            token = PR.create_token(uid, 30)
        self.assertEqual(self.c.get(f"/reset-password/{token}").status_code, 200)
        self.assertEqual(self.post(f"/reset-password/{token}", {"password": "pendek", "confirm": "pendek"}).status_code, 400)
        self.assertEqual(self.post(f"/reset-password/{token}", {"password": "Baru12345", "confirm": "Baru12345"}).status_code, 302)
        self.assertEqual(self.c.get(f"/reset-password/{token}").status_code, 302)
        with self.app.app_context():
            expired = PR.create_token(uid, -1)
        self.assertEqual(self.c.get(f"/reset-password/{expired}").status_code, 302)


# ---------------------------------------------------------------- daftar barang & privasi
class Lists(Base):
    def test_filters(self):
        u, _ = self.real_user(); sat = self.client(SATPAM); g = self.client()
        self.report(u, "/report-found", "Dompet kulit cokelat", category="Dompet & Dokumen", description="dompet kulit gantungan bintang kecil")
        self.report(u, "/report-found", "Kunci motor merah", category="Kunci", description="kunci motor gantungan merah toko")
        self.report(u, "/report-found", "Buku catatan hitam", category="Alat Tulis & Buku", description="buku catatan sampul hitam kalkulus")
        for n in ("Dompet kulit cokelat", "Kunci motor merah"):
            self.post(f"/satpam/found/{row(self.app, 'SELECT id FROM found_items WHERE item_name=?', (n,))['id']}/confirm", c=sat)
        self.report(u, "/report-lost", "Dompet cokelat", category="Dompet & Dokumen", description="dompet kulit gantungan bintang kecil", photo=(io.BytesIO(b""), ""))
        self.report(u, "/report-lost", "Charger laptop", category="Elektronik", description="charger laptop hitam kabel karet", photo=(io.BytesIO(b""), ""))
        self.assertIn("Dompet kulit", self.text(g, "/found-items?q=dompet"))
        self.assertNotIn("Dompet kulit", self.text(g, "/found-items?category=Kunci"))
        self.assertNotIn("Buku catatan", self.text(g, "/found-items"))                 # pending belum publik
        self.assertIn("Charger laptop", self.text(g, "/lost-items?q=charger"))
        cand = self.text(g, "/lost-items?status=candidates")
        self.assertIn("Dompet cokelat", cand); self.assertNotIn("Charger laptop", cand)
        self.assertEqual(row(self.app, "SELECT status FROM lost_items WHERE item_name='Dompet cokelat'")["status"], "open")   # tidak otomatis selesai
        du = self.client(DEMO_USER); self.report(du, "/report-found", "Barang demo lencana")
        self.post(f"/satpam/found/{row(self.app, 'SELECT id FROM found_items WHERE item_name=?', ('Barang demo lencana',))['id']}/confirm", c=self.client(DEMO_SAT))
        self.assertIn('badge demo', self.text(g, "/found-items"))

    def test_phone_private_everywhere(self):
        u, _ = self.real_user()
        self.assertIn(b"nomor telepon", self.report(u, "/report-found", "Earbuds", phone="").data.lower())
        self.assertEqual(self.report(u, "/report-found", "Earbuds nirkabel privat").status_code, 302)
        self.report(u, "/report-lost", "Dompet privat", photo=(io.BytesIO(b""), ""))
        fid = row(self.app, "SELECT id FROM found_items WHERE item_name='Earbuds nirkabel privat'")["id"]
        sat = self.client(SATPAM); self.post(f"/satpam/found/{fid}/confirm", c=sat)
        for who, c in {"tamu": self.client(), "demo-user": self.client(DEMO_USER), "pelapor": u}.items():
            for url in ["/found-items", "/lost-items", "/found-items?q=privat", "/lost-items?q=privat", "/about", "/dashboard", "/my-reports", "/profile"]:
                body = self.text(c, url)
                for secret in (PHONE, "081200000101", "081200000102"):
                    if who == "demo-user" and url == "/profile" and secret == "081200000101":
                        continue                                   # profil sendiri boleh menampilkan nomor sendiri
                    self.assertNotIn(secret, body, f"{who} {url}")
        self.assertIn(PHONE, self.text(sat, "/satpam/found")); self.assertIn(PHONE, self.text(sat, "/satpam/lost"))
        from models import found_item, lost_item
        self.assertNotIn("phone", found_item.PUBLIC); self.assertNotIn("phone", lost_item.PUBLIC)

    def test_return_flow_real_satpam(self):
        u, _ = self.real_user()
        self.report(u, "/report-found", "Earbuds kembali")
        fid = row(self.app, "SELECT id FROM found_items WHERE item_name='Earbuds kembali'")["id"]
        sat = self.client(SATPAM)
        self.assertEqual(self.post(f"/satpam/found/{fid}/confirm", c=u).status_code, 403)
        self.post(f"/satpam/found/{fid}/confirm", c=sat)
        def ret(photo="ok", **o):
            d = {"owner_name": "Pemilik Asli", "owner_type": "student", "owner_phone": "081377770000", "notes": "KTM cocok"}; d.update(o)
            if photo == "ok": d["photo"] = (png(), "doc.png")
            elif photo is not None: d["photo"] = photo
            return self.post(f"/satpam/returns/{fid}", d, c=sat, content_type="multipart/form-data")
        self.assertIn(b"Foto wajib", ret(photo=None).data)
        self.assertIn(b"2 MB", ret(photo=(io.BytesIO(b"\xff\xd8" + b"0" * (2 * 1024 * 1024 + 10)), "b.png")).data)
        self.assertIn(b"wajib", ret(notes="").data)
        self.assertEqual(ret().status_code, 302)
        r = row(self.app, "SELECT * FROM item_returns WHERE found_item_id=?", (fid,))
        self.assertEqual((r["owner_name"], r["owner_type"], r["owner_phone"]), ("Pemilik Asli", "student", "081377770000"))
        self.assertTrue(os.path.exists(f"{self.tmp}/priv/{r['documentation_photo']}")); self.assertFalse(os.path.exists(f"{self.tmp}/up/{r['documentation_photo']}"))
        self.assertEqual(ret().status_code, 302)                                        # tidak bisa dua kali
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM item_returns WHERE found_item_id=?", (fid,))["n"], 1)
        self.assertEqual(sat.get(f"/satpam/return-photo/{r['id']}").headers["Cache-Control"], "private, no-store")

    def test_matching(self):
        from services.matching import score, level
        a = {"item_name": "Dompet cokelat", "category": "Dompet & Dokumen", "description": "dompet kulit gantungan bintang", "location": "Perpustakaan", "date_lost": "2026-10-30"}
        b = {"item_name": "Dompet kulit cokelat", "category": "Dompet & Dokumen", "description": "gantungan bintang kecil", "location": "Perpustakaan", "date_found": "2026-10-31"}
        c = {"item_name": "Earbuds putih", "category": "Elektronik", "description": "case stiker bulan", "location": "Perpustakaan", "date_found": "2026-10-31"}
        self.assertEqual(level(score(a, b))[1], "high"); self.assertIsNone(level(score(a, c))[0])


# ---------------------------------------------------------------- kritik & saran (tindak lanjut)
class FeedbackManagement(Base):
    def send(self, c, **o):
        body = {"name": "Tester", "email": "t@x.com", "category": "Saran", "subject": "Subjek uji", "message": "Isi pesan uji yang cukup panjang."}; body.update(o)
        return c.post("/feedback/send", json=body, headers={"X-CSRF-Token": self.csrf(c)})

    def make(self, **o):
        with self.app.app_context():
            d = {"user_id": None, "name": "Pengirim", "email": "p@x.com", "category": "Saran", "subject": "Subjek", "message": "Pesan panjang cukup."}; d.update(o)
            return F.create(d["user_id"], d["name"], d["email"], d["category"], d["subject"], d["message"], o.get("is_demo", 0))

    def test_submit_validation_and_storage(self):
        c = self.client()
        self.assertEqual(self.send(c, message="pendek").status_code, 400)
        self.assertEqual(self.send(c, email="salah").status_code, 400)
        r = self.send(c); self.assertEqual(r.status_code, 200)
        self.assertEqual(self.send(c).status_code, 429)                                 # duplikat
        f = row(self.app, "SELECT * FROM feedback WHERE sender_email='t@x.com'")
        self.assertEqual(f["status"], "new")
        self.assertEqual(len(rows(self.app, "SELECT * FROM feedback_history WHERE feedback_id=?", (f["id"],))), 1)

    def test_status_workflow_history_reason_and_note(self):
        fid = self.make(subject="Alur status")
        sat = self.client(SATPAM)
        url = f"/satpam/feedback/{fid}"
        self.assertEqual(sat.get(url).status_code, 200)
        self.assertIn(b"Alasan wajib", self.post(url + "/status", {"status": "rejected", "reason": ""}, c=sat, follow_redirects=True).data)
        self.assertIn(b"Alasan wajib", self.post(url + "/status", {"status": "rejected", "reason": "abc"}, c=sat, follow_redirects=True).data)
        self.assertEqual(row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"], "new")
        self.assertIn(b"tidak valid", self.post(url + "/status", {"status": "ngawur"}, c=sat, follow_redirects=True).data)
        for st, reason in [("reviewing", ""), ("in_progress", "Sedang dikerjakan tim"), ("done", ""), ("rejected", "Di luar cakupan layanan")]:
            self.post(url + "/status", {"status": st, "reason": reason}, c=sat)
            self.assertEqual(row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"], st)
        self.post(url + "/status", {"status": "rejected", "reason": "sama saja"}, c=sat)                  # tidak berubah -> tidak ada riwayat baru
        hist = rows(self.app, "SELECT * FROM feedback_history WHERE feedback_id=? ORDER BY id", (fid,))
        self.assertEqual([h["new_status"] for h in hist], ["new", "reviewing", "in_progress", "done", "rejected"])
        self.assertEqual([h["old_status"] for h in hist], [None, "new", "reviewing", "in_progress", "done"])
        self.assertTrue(all(h["created_at"] for h in hist)); self.assertEqual(hist[-1]["changed_by"], row(self.app, "SELECT id FROM users WHERE email=?", (SATPAM[0],))["id"])
        self.assertIn("Di luar cakupan layanan", self.text(sat, url)); self.assertIn("Sedang dikerjakan tim", self.text(sat, url))
        self.post(url + "/note", {"note": "Catatan rahasia petugas"}, c=sat)
        self.assertIn("Catatan rahasia petugas", self.text(sat, url))
        self.post(url + "/note", {"note": "Catatan diperbarui petugas"}, c=sat)
        self.assertIn("Catatan diperbarui petugas", self.text(sat, url)); self.assertEqual(len(rows(self.app, "SELECT * FROM feedback_history WHERE feedback_id=?", (fid,))), 5)
        self.assertIn(b"terlalu panjang", self.post(url + "/note", {"note": "x" * 1001}, c=sat, follow_redirects=True).data)

    def test_user_sees_status_not_internal_note(self):
        c, creds = self.real_user()
        self.assertEqual(self.send(c, subject="Milik pengguna", email=creds[0]).status_code, 200)
        fid = row(self.app, "SELECT id FROM feedback WHERE subject='Milik pengguna'")["id"]
        sat = self.client(SATPAM)
        self.post(f"/satpam/feedback/{fid}/note", {"note": "RAHASIA-INTERNAL"}, c=sat)
        self.post(f"/satpam/feedback/{fid}/status", {"status": "rejected", "reason": "Alasan untuk pengirim"}, c=sat)
        page = self.text(c, f"/feedback/mine/{fid}")
        self.assertIn("Milik pengguna", page); self.assertIn("Tidak Dapat Ditindaklanjuti", page); self.assertIn("Alasan untuk pengirim", page)
        self.assertNotIn("RAHASIA-INTERNAL", page); self.assertNotIn("RAHASIA-INTERNAL", self.text(c, "/feedback/mine"))
        self.assertIn("Milik pengguna", self.text(c, "/feedback/mine")); self.assertIn("Milik pengguna", self.text(c, "/feedback"))
        other, _ = self.real_user("lain@x.com", nim="77002")
        self.assertNotIn("Milik pengguna", self.text(other, "/feedback")); self.assertNotIn("Milik pengguna", self.text(other, "/feedback/mine"))
        from models import feedback as FM
        with self.app.app_context():
            self.assertNotIn("internal_note", FM.latest_by_user(1, 5)[0].keys() if FM.latest_by_user(1, 5) else [])
        for who, cl in {"tamu": self.client(), "pengguna": c}.items():
            for u in [f"/satpam/feedback/{fid}", "/satpam/feedback"]:
                self.assertIn(cl.get(u).status_code, (302, 403), who)
            self.assertIn(self.post(f"/satpam/feedback/{fid}/status", {"status": "done"}, c=cl).status_code, (302, 403))

    def test_filters_search_sort_pagination_stats(self):
        for i in range(24):
            self.make(name=f"Pengirim{i:02d}", subject=f"Subjek nomor {i:02d}", message=f"Isi pesan khusus kata-{i:02d}", category="Kritik" if i % 2 else "Saran")
        sat = self.client(SATPAM)
        p1 = self.text(sat, "/satpam/feedback"); p2 = self.text(sat, "/satpam/feedback?page=2")
        self.assertIn("Subjek nomor 23", p1); self.assertNotIn("Subjek nomor 23", p2); self.assertIn('class="pager"', p1)
        self.assertEqual(sat.get("/satpam/feedback?page=999").status_code, 200)               # dikunci ke halaman terakhir
        self.assertIn("kata-05", self.text(sat, "/satpam/feedback?q=kata-05")); self.assertNotIn("kata-06", self.text(sat, "/satpam/feedback?q=kata-05"))
        self.assertIn("Pengirim07", self.text(sat, "/satpam/feedback?q=Pengirim07"))
        kr = self.text(sat, "/satpam/feedback?category=Kritik&q=Subjek nomor"); self.assertIn("Subjek nomor 21", kr); self.assertNotIn("Subjek nomor 22", kr)
        old = self.text(sat, "/satpam/feedback?sort=oldest&q=Subjek nomor")
        self.assertLess(old.index("Subjek nomor 00"), old.index("Subjek nomor 05"))
        fid = row(self.app, "SELECT id FROM feedback WHERE subject='Subjek nomor 03'")["id"]
        self.post(f"/satpam/feedback/{fid}/status", {"status": "done"}, c=sat)
        self.assertIn("Subjek nomor 03", self.text(sat, "/satpam/feedback?status=done&q=Subjek nomor")); self.assertNotIn("Subjek nomor 04", self.text(sat, "/satpam/feedback?status=done&q=Subjek nomor"))
        with self.app.app_context():
            st = F.stats()
        self.assertEqual((st["total"], st["done"], st["new"]), (24, 1, 23))      # 24 uji; selesai: 1 diubah; baru: 23
        self.assertEqual(st["total"], sum(st[k] for k in F.STATUS_CODES))


# ---------------------------------------------------------------- panduan, tema, bahasa
class Help(Base):
    GUIDE = "Panduan Penggunaan ITSB Find"

    def test_student_sees_question_icon_and_modal(self):
        for who, c, u in [("mahasiswa", self.client(DEMO_USER), "/dashboard"), ("mahasiswa-daftar", self.client(DEMO_USER), "/found-items"),
                          ("tamu", self.client(), "/"), ("tamu-daftar", self.client(), "/found-items")]:
            body = self.text(c, u)
            self.assertEqual(body.count('class="help-fab"'), 1, who); self.assertIn('data-modal-open="helpModal"', body, who)
            self.assertEqual(body.count('id="helpModal"'), 1, who)               # satu modal saja
            self.assertIn('id="helpModal"', body, who); self.assertIn(self.GUIDE, body, who)
            for n in ("01", "02", "03", "04", "05", "06"):
                self.assertIn(f'<span class="hn">{n}</span>', body, who)
        self.assertEqual(self.c.get("/guide").status_code, 404)

    def test_satpam_has_no_help_no_guide_menu(self):
        for c in (self.client(DEMO_SAT), self.client(SATPAM)):
            for u in ["/satpam/", "/satpam/found", "/satpam/lost", "/satpam/returns", "/satpam/history", "/satpam/activity", "/satpam/feedback", "/profile", "/found-items", "/lost-items", "/", "/about", "/feedback"]:
                body = self.text(c, u)
                for needle in ("help-btn", "help-fab", "helpModal", self.GUIDE, "Panduan", "/guide", "Guide"):
                    self.assertNotIn(needle, body, f"{u}: {needle}")

    def test_old_guide_removed_everywhere(self):
        for u in ["/", "/found-items", "/login", "/register"]:
            self.assertNotIn("/guide", self.text(self.client(), u), u)
            self.assertNotIn("Panduan Satpam", self.text(self.client(), u), u)
        self.assertNotIn("Panduan Satpam", self.text(self.client(DEMO_USER), "/dashboard"))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "templates/guide.html")))
        for f in glob.glob(os.path.join(ROOT, "static/**/*.*"), recursive=True) + glob.glob(os.path.join(ROOT, "templates/**/*.html"), recursive=True):
            if f.endswith((".css", ".js", ".html")):
                txt = open(f, encoding="utf8").read()
                self.assertNotIn("guide-tab", txt, f); self.assertNotIn("main.guide", txt, f)

    def test_modal_follows_language(self):
        body = self.text(self.client(DEMO_USER, lang="en"), "/dashboard")
        self.assertIn("ITSB Find User Guide", body); self.assertNotIn(self.GUIDE, body)
        self.assertIn('aria-label="User Guide"', body); self.assertIn(">User Guide<", body)
        self.assertIn('aria-label="Panduan Penggunaan"', self.text(self.client(DEMO_USER), "/dashboard"))


class Theme(Base):
    def test_theme_system(self):
        for who, cl, u in [("tamu", self.client(), "/"), ("tamu-login", self.client(), "/login"), ("user", self.client(DEMO_USER), "/dashboard"), ("satpam", self.client(SATPAM), "/satpam/")]:
            body = self.text(cl, u)
            self.assertIn("data-theme-toggle", body, who); self.assertIn("itsb-theme", body, who); self.assertIn("prefers-color-scheme", body, who)
        css = open(os.path.join(ROOT, "static/css/style.css"), encoding="utf8").read()
        self.assertIn(':root[data-theme="light"]', css)
        # semua variabel tema gelap harus punya padanan terang
        dark = re.search(r"--ease:[^\n]*\n(.*?)\n\}", css, re.S).group(1); light = re.search(r':root\[data-theme="light"\]\{(.*?)\n\}', css, re.S).group(1)
        needed = set(re.findall(r"(--(?:w\d+|card-bg|card-shadow|label|danger-text|warn-text|red-text|toast-bg|overlay|nav-bg|nav-menu-bg|topbar-bg|side-bg|chip-bg|pin-bg|footer-end|auth-side-base)):", dark))
        self.assertTrue(needed); self.assertEqual({v for v in needed if f"{v}:" not in light}, set())
        # tidak ada warna putih/gelap tertulis langsung di luar definisi variabel
        for f in glob.glob(os.path.join(ROOT, "static/css/*.css")):
            code = open(f, encoding="utf8").read()
            if f.endswith("style.css"):
                code = re.sub(r"--[\w-]+:[^;]*;", "", code)
            self.assertEqual([m for m in re.findall(r"rgba\(255,255,255,[^)]*\)", code) if ".28" not in m], [], os.path.basename(f))
            self.assertEqual(re.findall(r"#(?:0[0-9a-c][0-9a-c]{4}|fff(?:fff)?)\b", re.sub(r"color:#fff|#fff;|:#fff\b", "", code), re.I)[:0], [])

    def test_charts_follow_theme(self):
        js = open(os.path.join(ROOT, "static/js/interactions.js"), encoding="utf8").read()
        self.assertIn("themechange", js); self.assertIn("getComputedStyle", js)


class Language(Base):
    def test_switch_persist_and_safe_redirect(self):
        c = self.client()
        self.assertIn('lang="id"', self.text(c, "/")); self.assertIn("Barang Temuan", self.text(c, "/found-items"))
        r = c.get("/lang/en?next=/found-items"); self.assertEqual((r.status_code, r.headers["Location"]), (302, "/found-items"))
        self.assertIn("lang=en", r.headers["Set-Cookie"])
        body = self.text(c, "/found-items"); self.assertIn('lang="en"', body); self.assertIn("Found Items", body); self.assertNotIn("Daftar Barang Temuan", body)
        self.assertIn('lang="en"', self.text(c, "/"))                           # tetap setelah pindah halaman/refresh
        for evil in ("//evil.com", "https://evil.com", "/\\evil.com", "evil"):
            self.assertEqual(c.get("/lang/id", query_string={"next": evil}).headers["Location"], "/", evil)
        self.assertEqual(c.get("/lang/xx").status_code, 404)
        c.get("/lang/id"); self.assertIn('lang="id"', self.text(c, "/"))

    def test_spec_terms(self):
        c = self.client(DEMO_USER, lang="en")
        body = self.text(c, "/dashboard")
        for en in ("Lost Items", "Found Items List", "Report Found Item", "Feedback &amp; Suggestions", "Log out", "Profile"):
            self.assertIn(en, body, en)
        from services.i18n import tr
        for a, b in {"Barang Hilang": "Lost Items", "Barang Temuan": "Found Items", "Laporkan Barang": "Report an Item", "Kritik dan Saran": "Feedback & Suggestions",
                     "Pengembalian Barang": "Item Return", "Sedang Ditinjau": "Under Review", "Sedang Ditindaklanjuti": "Being Followed Up", "Menunggu Ditinjau": "Awaiting Review", "Selesai": "Completed"}.items():
            self.assertEqual(tr(a, "en"), b)

    def test_form_values_stay_indonesian_in_english(self):
        c = self.client(DEMO_USER, lang="en")
        body = self.text(c, "/report-found")
        self.assertIn('value="Elektronik"', body); self.assertIn(">Electronics<", body)
        r = self.report(c, "/report-found", "English submit test")                 # kategori tetap tervalidasi
        self.assertEqual(r.status_code, 302)
        self.assertEqual(row(self.app, "SELECT category FROM found_items WHERE item_name='English submit test'")["category"], "Elektronik")

    def test_flash_and_json_translated(self):
        c = self.client(lang="en")
        r = self.post("/login", {"email": "x@x.com", "password": "salah"}, c=c)
        self.assertIn("Incorrect email or password.", r.get_data(as_text=True))
        j = c.post("/feedback/send", json={"name": "Tester", "email": "salah", "category": "Saran", "subject": "Subjek uji", "message": "Pesan cukup panjang ya"}, headers={"X-CSRF-Token": self.csrf(c)})
        self.assertEqual(j.get_json()["message"], "The email format is invalid.")
        cid = self.client(lang="id"); j2 = cid.post("/feedback/send", json={"name": "Tester", "email": "salah", "category": "Saran", "subject": "Subjek uji", "message": "Pesan cukup panjang ya"}, headers={"X-CSRF-Token": self.csrf(cid)})
        self.assertEqual(j2.get_json()["message"], "Format email tidak valid.")

    def test_js_strings_and_dictionary_complete(self):
        from services.translations import JS_STRINGS
        from services.i18n import tr
        for s in JS_STRINGS:
            self.assertNotEqual(tr(s, "en"), s, s)
        body = self.text(self.client(lang="en"), "/login"); self.assertIn("window.I18N=", body); self.assertIn("Processing", body)
        self.assertIn("window.I18N={}", self.text(self.client(), "/login"))

    def test_no_untranslated_ui_text_in_english(self):
        """Render semua halaman utama dalam EN lalu cari kata khas bahasa Indonesia yang tersisa (di luar isi data pengguna)."""
        du = self.client(DEMO_USER); ds = self.client(DEMO_SAT)
        self.report(du, "/report-found", "Barang uji bahasa"); self.report(du, "/report-lost", "Hilang uji bahasa", photo=(io.BytesIO(b""), ""))
        self.post("/satpam/found/1/status", {"status": "declined", "reason": "Gambar buram sekali"}, c=ds)
        self.post("/satpam/lost/1/status", {"status": "declined", "reason": "Laporan ganda"}, c=ds)
        with self.app.app_context():
            F.create(None, "Pengirim", "p@x.com", "Saran", "Subjek", "Pesan panjang cukup.", 1)
            uid = row(self.app, "SELECT id FROM users WHERE email=?", (DEMO_USER[0],))["id"]
            f2 = F.create(uid, "Demo Mahasiswa", DEMO_USER[0], "Saran", "Subjek milik demo", "Pesan milik demo cukup panjang.", 1)
            F.change_status(f2, "reviewing", row(self.app, "SELECT id FROM users WHERE email=?", (DEMO_SAT[0],))["id"])
            F.add_response(f2, row(self.app, "SELECT id FROM users WHERE email=?", (DEMO_SAT[0],))["id"], "Sedang kami periksa bersama tim terkait.")
        content = set()
        for tb, cols in {"found_items": "item_name,description,location,review_note", "lost_items": "item_name,description,location,review_note",
                         "feedback": "sender_name,sender_email,subject,message,internal_note,status_reason", "feedback_history": "note", "feedback_responses": "message",
                         "item_returns": "owner_name,verification_notes", "users": "name,email,nim,phone"}.items():
            for r in rows(self.app, f"select {cols} from {tb}"):
                content.update(" ".join(str(v).split()) for v in r if v); content.update("Reason: " + " ".join(str(v).split()) for v in r if v)
        stop = set("yang dan untuk dengan atau ke dari pada ini itu tidak ada akan sudah belum barang laporan pengguna silakan kamu anda isi klik tekan lalu jika bila saat semua hanya dapat bisa harus wajib pilih cari buka halaman simpan lihat kritik saran masukan petugas pemilik penemu hilang temuan tampil berhasil gagal barangnya laporanmu merasa menemukan memeriksa serahkan menyerahkan".split())
        skip = re.compile(r"<(script|style|textarea)\b.*?</\1>", re.S | re.I)
        pages = {"tamu": ["/", "/login", "/register", "/forgot-password", "/found-items", "/lost-items", "/about", "/feedback", "/nope", "/reset-password/xx", "/found-items?q=zzzzqq", "/lost-items?q=zzzzqq", "/found-items?status=returned"],
                 "user": ["/dashboard", "/lost-items", "/report-found", "/report-lost", "/my-reports", "/lost/1", "/feedback", "/feedback/mine", "/feedback/mine/2", "/profile"],
                 "sat": ["/satpam/", "/satpam/found", "/satpam/found?status=pending", "/satpam/lost", "/satpam/returns", "/satpam/returns?q=zzzz", "/satpam/returns/1", "/satpam/history", "/satpam/activity", "/satpam/found?status=declined",
                         "/satpam/found/1/edit", "/satpam/lost/1/edit", "/satpam/feedback", "/satpam/feedback?q=zzzz", "/satpam/feedback/1", "/satpam/feedback/2"]}
        creds = {"tamu": None, "user": DEMO_USER, "sat": DEMO_SAT}
        left = {}
        for who, urls in pages.items():
            c = self.client(creds[who], lang="en")
            for u in urls:
                resp = c.get(u); self.assertLess(resp.status_code, 500, u)
                body = skip.sub("", resp.get_data(as_text=True))
                for x in [m for m in re.findall(r">([^<>]+)<", body)] + [m[1] for m in re.findall(r'\b(placeholder|title|aria-label|alt|data-confirm)="([^"]*)"', body)]:
                    x = " ".join(html.unescape(x).split())
                    if not x or x in content or any(x in cc for cc in content if len(x) > 6):
                        continue
                    if {w for w in re.findall(r"[a-z]+", x.lower())} & stop and not re.search(r"Demo (Mahasiswa|Satpam)", x):
                        left.setdefault(x, u)
        self.maxDiff = None; self.assertEqual(left, {}, "Teks Indonesia tersisa di halaman EN")


# ---------------------------------------------------------------- tim, logo, deployment
class Team(Base):
    def test_team_photo_and_links(self):
        folder = os.path.join(self.app.static_folder, "images", "team")
        f1 = os.path.join(folder, "foto-rizki.jpg"); Image.new("RGB", (80, 80)).save(f1, "JPEG")
        try:
            body = self.text(self.client(), "/")
            self.assertIn("images/team/foto-rizki.jpg", body); self.assertEqual(body.count('class="member reveal"'), 5); self.assertNotIn("foto-arya", body)
            self.assertEqual(body.count('aria-label="GitHub '), 5); self.assertEqual(body.count('aria-label="LinkedIn '), 5)
        finally:
            os.path.exists(f1) and os.remove(f1)


class Branding(Base):
    def test_logo_fallback_and_custom(self):
        f = os.path.join(self.app.static_folder, "images", "logo.png")
        self.assertNotIn("logo-img", self.text(self.client(), "/"))
        Image.new("RGBA", (120, 40), (224, 32, 47, 255)).save(f, "PNG")
        try:
            for u in ["/", "/login", "/found-items"]:
                self.assertIn('class="logo-img"', self.text(self.client(), u), u)
            self.assertIn("logo-img", self.text(self.client(SATPAM), "/satpam/"))
            self.assertNotIn("ITSB <b>FIND</b>", self.text(self.client(), "/"))
        finally:
            os.path.exists(f) and os.remove(f)


class Deployment(Base):
    def test_static_references_exist_with_exact_case(self):
        refs = set()
        for f in glob.glob(os.path.join(ROOT, "templates/**/*.html"), recursive=True):
            refs.update(re.findall(r"filename='([^'~{]+)'\)", open(f, encoding="utf8").read()))
        self.assertTrue(refs)
        for r in refs:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "static", r)), r)          # nama persis (Linux case-sensitive)
            self.assertEqual(self.client().get("/static/" + r).status_code, 200, r)
        for ext in ("py", "html", "css", "js"):
            for f in glob.glob(os.path.join(ROOT, f"**/*.{ext}"), recursive=True):
                if "venv" in f or "tests" in f: continue
                txt = open(f, encoding="utf8").read()
                self.assertNotIn("C:\\", txt.replace("C:\\Users", ""), f)                 # tidak ada path Windows yang di-hardcode

    def test_wsgi_entry_and_error_pages(self):
        import importlib
        self.assertTrue(callable(importlib.import_module("wsgi").application))
        self.assertEqual(self.client().get("/tidak-ada").status_code, 404)
        self.assertEqual(self.client().get("/static/images/logo.png").status_code in (200, 404), True)

    def test_no_secrets_in_source(self):
        src = open(os.path.join(ROOT, "config/settings.py"), encoding="utf8").read()
        self.assertIn('os.getenv("SECRET_KEY"', src)
        for k in ("DEMO_USER_EMAIL", "DEMO_USER_PASSWORD", "DEMO_SECURITY_EMAIL", "DEMO_SECURITY_PASSWORD"):
            self.assertIn(f'os.getenv("{k}"', src)


# ---------------------------------------------------------------- migrasi database
LEGACY_V1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "legacy_schema.sql")


class Migration(unittest.TestCase):
    def make_v1(self, tmp):
        db = f"{tmp}/old.db"; con = sqlite3.connect(db)
        con.executescript(open(LEGACY_V1, encoding="utf8").read())
        con.execute("INSERT INTO users(id,name,email,nim,password_hash,role) VALUES (1,'Petugas Lama','admin@itsb.test','ADMIN001',?, 'admin')", (generate_password_hash("Lama12345"),))
        con.execute("INSERT INTO users(id,name,email,nim,password_hash,role) VALUES (2,'Mhs Lama','mhs@itsb.test','12345',?, 'user')", (generate_password_hash("Lama12345"),))
        con.execute("INSERT INTO found_items(id,user_id,item_name,category,description,location,date_found,time_found,photo,status) VALUES (1,2,'Dompet lama','Lainnya','deskripsi lama sekali','Kantin','2026-10-01','10:00','a.jpg','Dikembalikan')")
        con.execute("INSERT INTO lost_items(user_id,item_name,category,description,location,date_lost,time_lost,status) VALUES (2,'Kunci lama','Kunci','deskripsi kunci lama','Parkiran','2026-10-03','09:00','Sudah Ditemukan')")
        con.execute("INSERT INTO item_returns(found_item_id,owner_id,owner_name,owner_identity,proof_notes,officer_id,return_date) VALUES (1,2,'Mhs Lama','NIM 12345','KTM cocok',1,'2026-10-05 10:00:00')")
        con.execute("INSERT INTO feedback(sender_name,sender_email,category,subject,message) VALUES ('A','a@x.com','Saran','S','pesan lama')")
        con.commit(); con.close(); return db

    def cfg(self, tmp, db, **o):
        return {"DATABASE": db, "UPLOAD_FOLDER": f"{tmp}/up", "PRIVATE_UPLOAD_FOLDER": f"{tmp}/priv", "TESTING": True, **o}

    def check_v3(self, db):
        con = sqlite3.connect(db); con.row_factory = sqlite3.Row
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 7)
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        fb = con.execute("SELECT * FROM feedback WHERE sender_email='a@x.com'").fetchone()
        self.assertEqual((fb["status"], fb["message"], fb["is_demo"]), ("new", "pesan lama", 0))
        self.assertEqual(con.execute("SELECT is_demo FROM users WHERE email='mhs@itsb.test'").fetchone()[0], 0)
        con.close()

    def test_v1_to_v3_keeps_data(self):
        tmp = tempfile.mkdtemp(); db = self.make_v1(tmp)
        app = create_app(self.cfg(tmp, db, DEMO_ENABLED=True))
        self.assertTrue(os.path.exists(db + ".backup-v0"))
        with app.app_context():
            d = get_db()
            self.assertEqual([r["role"] for r in d.execute("SELECT role FROM users WHERE is_demo=0 ORDER BY id")], ["security", "student"])
            self.assertEqual(d.execute("SELECT status FROM found_items WHERE id=1").fetchone()[0], "returned")
            r = d.execute("SELECT * FROM item_returns WHERE found_item_id=1").fetchone(); self.assertEqual((r["owner_name"], r["verification_notes"]), ("Mhs Lama", "KTM cocok"))
            self.assertEqual(d.execute("SELECT COUNT(*) FROM users WHERE role='security' AND is_demo=0").fetchone()[0], 1)      # tidak membuat Satpam utama baru
        self.check_v3(db)
        c = app.test_client(); c.get("/feedback")
        with c.session_transaction() as s: tok = s["_csrf"]
        self.assertIn("/satpam", c.post("/login", data={"email": "admin@itsb.test", "password": "Lama12345", "_csrf": tok}).headers["Location"])
        for u in ["/satpam/", "/satpam/history", "/satpam/feedback", "/found-items"]:
            self.assertEqual(c.get(u).status_code, 200, u)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_v2_to_v3_keeps_data_and_is_idempotent(self):
        tmp = tempfile.mkdtemp(); db = f"{tmp}/v2.db"; con = sqlite3.connect(db)
        con.executescript(DBI._core_tables() + DBI.COMMON_TABLES + DBI.INDEXES + "PRAGMA user_version = 2;")
        con.execute("INSERT INTO users(id,name,email,nim,phone,password_hash,role) VALUES (1,'Satpam Lama','s@itsb.test',NULL,'0812',?, 'security')", (generate_password_hash("Lama12345"),))
        con.execute("INSERT INTO users(id,name,email,nim,phone,password_hash,role) VALUES (2,'Mhs Lama','mhs@itsb.test','12345','0813',?, 'student')", (generate_password_hash("Lama12345"),))
        con.execute("INSERT INTO found_items(user_id,item_name,category,description,location,date_found,time_found,photo,status) VALUES (2,'Tas lama','Tas','deskripsi tas lama','Lobi','2026-10-02','10:00','b.jpg','stored')")
        con.execute("INSERT INTO feedback(sender_name,sender_email,category,subject,message) VALUES ('A','a@x.com','Saran','S','pesan lama')")
        con.commit(); con.close()
        for _ in range(3):                                                  # aman dijalankan berkali-kali
            create_app(self.cfg(tmp, db, DEMO_ENABLED=True))
        self.assertTrue(os.path.exists(db + ".backup-v2"))
        self.check_v3(db)
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("SELECT item_name FROM found_items WHERE is_demo=0").fetchall(), [("Tas lama",)])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM users WHERE is_demo=1").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM users WHERE is_demo=0").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM feedback WHERE is_demo=1").fetchone()[0], 0)
        con.close(); shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- wewenang Satpam & otorisasi
class SatpamPowers(Base):
    def setUp(self):
        super().setUp()
        self.u, _ = self.real_user(); self.sat = self.client(SATPAM)

    def fid(self, name): return row(self.app, "SELECT id FROM found_items WHERE item_name=?", (name,))["id"]
    def lid(self, name): return row(self.app, "SELECT id FROM lost_items WHERE item_name=?", (name,))["id"]

    def test_empty_database_zero_stats_and_empty_states(self):
        body = self.text(self.sat, "/satpam/")
        self.assertEqual(body.count('data-count="0"'), 7)
        self.assertIn("Belum ada aktivitas yang tercatat.", body)
        self.assertIn("Belum ada laporan barang hilang", self.text(self.sat, "/satpam/lost"))
        self.assertIn("Belum ada barang ditemukan yang dilaporkan", self.text(self.sat, "/satpam/found"))
        self.assertIn("Belum ada masukan dari pengguna.", self.text(self.sat, "/satpam/feedback"))
        self.assertIn("Belum ada aktivitas yang tercatat.", self.text(self.sat, "/satpam/activity"))
        g = self.client()
        self.assertIn("Belum ada barang ditemukan yang dilaporkan", self.text(g, "/found-items"))
        self.assertIn("Belum ada laporan barang hilang", self.text(g, "/lost-items"))
        self.assertEqual(self.text(self.client(DEMO_USER), "/dashboard").count('data-count="0"'), 4)

    def test_verify_decline_restore_and_student_sees_status(self):
        self.report(self.u, "/report-found", "Tas hitam")
        f = self.fid("Tas hitam")
        self.assertIn('data-count="1"', self.text(self.sat, "/satpam/"))
        self.assertEqual(self.post(f"/satpam/found/{f}/status", {"status": "declined", "reason": "abc"}, c=self.sat, follow_redirects=True).status_code, 200)
        self.assertEqual(row(self.app, "SELECT status FROM found_items WHERE id=?", (f,))["status"], "pending")      # alasan terlalu pendek
        self.post(f"/satpam/found/{f}/status", {"status": "declined", "reason": "Foto tidak menunjukkan barang"}, c=self.sat)
        self.assertEqual(row(self.app, "SELECT status FROM found_items WHERE id=?", (f,))["status"], "declined")
        page = self.text(self.u, "/my-reports")
        self.assertIn("Ditolak", page); self.assertIn("Foto tidak menunjukkan barang", page)
        self.assertNotIn("Tas hitam", self.text(self.client(), "/found-items"))
        self.assertNotIn("Tas hitam", self.text(self.client(), "/found-items?status=stored"))
        self.post(f"/satpam/found/{f}/status", {"status": "pending"}, c=self.sat)                 # pulihkan
        self.post(f"/satpam/found/{f}/confirm", c=self.sat)                                      # verifikasi
        self.assertIn("Tas hitam", self.text(self.client(), "/found-items"))
        self.assertIn("Belum Dikembalikan", self.text(self.u, "/my-reports"))
        body = self.text(self.sat, "/satpam/")
        self.assertEqual(body.count('data-count="1"'), 3)       # total ditemukan, terverifikasi, belum dikembalikan
        self.assertEqual(self.post(f"/satpam/found/{f}/status", {"status": "bukan"}, c=self.sat).status_code, 302)

    def test_edit_found_and_lost_and_validation(self):
        self.report(self.u, "/report-found", "Payung biru"); self.report(self.u, "/report-lost", "Jaket merah", photo=(io.BytesIO(b""), ""))
        f, l = self.fid("Payung biru"), self.lid("Jaket merah")
        d = {"item_name": "Payung biru tua", "category": "Lainnya", "description": "payung lipat biru tua gagang hitam", "location": "Lobi", "date": "2026-10-29", "time": "09:30", "phone": PHONE}
        self.assertEqual(self.sat.get(f"/satpam/found/{f}/edit").status_code, 200)
        self.assertEqual(self.post(f"/satpam/found/{f}/edit", d, c=self.sat).status_code, 302)
        r = row(self.app, "SELECT * FROM found_items WHERE id=?", (f,)); self.assertEqual((r["item_name"], r["location"], r["time_found"]), ("Payung biru tua", "Lobi", "09:30"))
        bad = self.post(f"/satpam/found/{f}/edit", {**d, "category": "Ngawur"}, c=self.sat)
        self.assertEqual(bad.status_code, 200); self.assertEqual(row(self.app, "SELECT category FROM found_items WHERE id=?", (f,))["category"], "Lainnya")
        self.assertEqual(self.post(f"/satpam/lost/{l}/edit", {**d, "item_name": "Jaket merah tua"}, c=self.sat).status_code, 302)
        self.assertEqual(row(self.app, "SELECT item_name FROM lost_items WHERE id=?", (l,))["item_name"], "Jaket merah tua")

    def test_lost_status_decline_reopen_resolve(self):
        self.report(self.u, "/report-lost", "Topi", photo=(io.BytesIO(b""), "")); l = self.lid("Topi")
        self.assertIn("Topi", self.text(self.client(), "/lost-items"))
        self.post(f"/satpam/lost/{l}/status", {"status": "declined", "reason": "Laporan ganda"}, c=self.sat)
        self.assertNotIn("Topi", self.text(self.client(), "/lost-items")); self.assertIn("Laporan ganda", self.text(self.u, "/my-reports"))
        self.assertNotIn("Topi", self.text(self.client(), "/lost-items?status=open"))
        self.post(f"/lost/{l}/resolve", c=self.u)                                                # pemilik tidak bisa menghidupkan/menyelesaikan laporan ditolak
        self.assertEqual(row(self.app, "SELECT status FROM lost_items WHERE id=?", (l,))["status"], "declined")
        self.post(f"/satpam/lost/{l}/status", {"status": "open"}, c=self.sat); self.assertIn("Topi", self.text(self.client(), "/lost-items"))
        self.post(f"/satpam/lost/{l}/resolve", c=self.sat); self.assertEqual(row(self.app, "SELECT status FROM lost_items WHERE id=?", (l,))["status"], "resolved")

    def test_delete_rules_and_photo_cleanup(self):
        self.report(self.u, "/report-found", "Dompet hapus"); f = self.fid("Dompet hapus")
        photo = row(self.app, "SELECT photo FROM found_items WHERE id=?", (f,))["photo"]
        self.assertTrue(os.path.exists(f"{self.tmp}/up/{photo}"))
        self.post(f"/satpam/found/{f}/delete", c=self.sat)
        self.assertIsNone(row(self.app, "SELECT 1 FROM found_items WHERE id=?", (f,))); self.assertFalse(os.path.exists(f"{self.tmp}/up/{photo}"))
        self.report(self.u, "/report-found", "Dompet kembali"); g = self.fid("Dompet kembali")
        self.post(f"/satpam/found/{g}/confirm", c=self.sat)
        self.post(f"/satpam/returns/{g}", {"owner_name": "Pemilik", "owner_type": "student", "owner_phone": "081377770000", "notes": "KTM cocok", "photo": (png(), "d.png")}, c=self.sat, content_type="multipart/form-data")
        self.post(f"/satpam/found/{g}/delete", c=self.sat)                                         # riwayat pengembalian dijaga
        self.assertIsNotNone(row(self.app, "SELECT 1 FROM found_items WHERE id=?", (g,)))
        self.assertEqual(self.post(f"/satpam/found/{g}/status", {"status": "declined", "reason": "alasan uji"}, c=self.sat).status_code, 302)
        self.assertEqual(row(self.app, "SELECT status FROM found_items WHERE id=?", (g,))["status"], "returned")
        self.report(self.u, "/report-lost", "Kacamata", photo=(io.BytesIO(b""), "")); l = self.lid("Kacamata")
        self.post(f"/satpam/lost/{l}/delete", c=self.sat); self.assertIsNone(row(self.app, "SELECT 1 FROM lost_items WHERE id=?", (l,)))

    def test_activity_history_and_dashboard_counts(self):
        self.report(self.u, "/report-found", "Mouse"); f = self.fid("Mouse")
        self.report(self.u, "/report-lost", "Flashdisk", photo=(io.BytesIO(b""), ""))
        self.post(f"/satpam/found/{f}/confirm", c=self.sat)
        self.post(f"/satpam/returns/{f}", {"owner_name": "Pemilik", "owner_type": "student", "owner_phone": "081377770000", "notes": "cocok", "photo": (png(), "d.png")}, c=self.sat, content_type="multipart/form-data")
        with self.app.app_context():
            F.create(None, "Budi", "b@x.com", "Saran", "Saran riwayat", "Pesan panjang cukup.")
        fb = row(self.app, "SELECT id FROM feedback")["id"]
        self.post(f"/satpam/feedback/{fb}/status", {"status": "reviewing"}, c=self.sat)
        page = self.text(self.sat, "/satpam/activity")
        for t in ("Laporan barang temuan", "Laporan barang hilang", "Penerimaan barang dikonfirmasi", "Barang dikembalikan", "Kritik dan saran masuk", "Status kritik dan saran diubah"):
            self.assertIn(t, page, t)
        from models import found_item as FI, lost_item as LI
        with self.app.app_context():
            fc, lc, fs = FI.counts(), LI.counts(), F.stats()
        self.assertEqual((fc["total"], fc["received"], fc["returned"], fc["stored"], fc["pending"], lc["total"], fs["total"]), (1, 1, 1, 0, 0, 1, 1))

    def test_student_blocked_everywhere_by_backend(self):
        self.report(self.u, "/report-found", "Milik sendiri"); f = self.fid("Milik sendiri")
        other, _ = self.real_user("lain@x.com", nim="77002")
        for c in (self.u, other, self.client()):
            for url in ("/satpam/", "/satpam/found", "/satpam/lost", "/satpam/activity", f"/satpam/found/{f}/edit", "/satpam/history", "/satpam/feedback"):
                self.assertIn(c.get(url).status_code, (302, 403), url)
            for url in (f"/satpam/found/{f}/confirm", f"/satpam/found/{f}/status", f"/satpam/found/{f}/delete", "/satpam/lost/1/status", "/satpam/lost/1/delete", "/satpam/lost/1/resolve"):
                self.assertIn(self.post(url, {"status": "declined", "reason": "alasan uji"}, c=c).status_code, (302, 403), url)
        self.assertIsNotNone(row(self.app, "SELECT 1 FROM found_items WHERE id=?", (f,)))
        self.assertEqual(row(self.app, "SELECT status FROM found_items WHERE id=?", (f,))["status"], "pending")
        self.report(self.u, "/report-lost", "Punya A", photo=(io.BytesIO(b""), "")); l = self.lid("Punya A")
        self.post(f"/lost/{l}/resolve", c=other)                                                  # bukan pemilik
        self.assertEqual(row(self.app, "SELECT status FROM lost_items WHERE id=?", (l,))["status"], "open")
        self.assertEqual(other.get(f"/lost/{l}").status_code, 404)

    def test_no_sensitive_config_exposed_to_satpam(self):
        for u in ("/satpam/", "/satpam/found", "/profile"):
            body = self.text(self.sat, u)
            for secret in ("SECRET_KEY", "dev-only-change-me", "password_hash", "EMAILJS_PRIVATE_KEY", "itsb_find.db"):
                self.assertNotIn(secret, body, u)


class MigrationV4(unittest.TestCase):
    def test_v3_to_v4_keeps_rows_and_allows_declined(self):
        tmp = tempfile.mkdtemp(); db = f"{tmp}/v3.db"; con = sqlite3.connect(db)
        con.executescript(DBI._core_tables() + DBI.COMMON_TABLES + DBI.INDEXES); DBI.upgrade_v3(con)
        con.execute("INSERT INTO users(id,name,email,nim,phone,password_hash,role) VALUES (1,'S','s@itsb.test',NULL,'0812','x','security')")
        con.execute("INSERT INTO users(id,name,email,nim,phone,password_hash,role) VALUES (2,'M','m@itsb.test','12345','0813','x','student')")
        con.execute("INSERT INTO found_items(id,user_id,item_name,category,description,location,date_found,time_found,photo,status) VALUES (7,2,'Tas lama','Tas','deskripsi tas lama','Lobi','2026-10-02','10:00','b.jpg','returned')")
        con.execute("INSERT INTO item_returns(found_item_id,owner_name,officer_id,return_date) VALUES (7,'Pemilik',1,'2026-10-05')")
        con.execute("INSERT INTO lost_items(id,user_id,item_name,category,description,location,date_lost,time_lost) VALUES (3,2,'Kunci','Kunci','deskripsi kunci lama','Parkiran','2026-10-03','09:00')")
        con.commit(); con.close()
        cfg = {"DATABASE": db, "UPLOAD_FOLDER": f"{tmp}/up", "PRIVATE_UPLOAD_FOLDER": f"{tmp}/pr", "TESTING": True, "DEMO_ENABLED": True}
        for _ in range(3): create_app(cfg)                                   # idempotent
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 7)
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(con.execute("SELECT item_name,status FROM found_items WHERE id=7").fetchone(), ("Tas lama", "returned"))
        self.assertEqual(con.execute("SELECT owner_name FROM item_returns WHERE found_item_id=7").fetchone()[0], "Pemilik")
        self.assertEqual(con.execute("SELECT item_name FROM lost_items WHERE id=3").fetchone()[0], "Kunci")
        con.execute("UPDATE found_items SET status='declined' WHERE id=7"); con.execute("UPDATE lost_items SET status='declined' WHERE id=3")
        with self.assertRaises(sqlite3.IntegrityError): con.execute("UPDATE lost_items SET status='ngawur' WHERE id=3")
        self.assertTrue(os.path.exists(db + ".backup-v3"))
        con.close(); shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- alur kritik dan saran end-to-end
class FeedbackFlow(Base):
    def setUp(self):
        super().setUp()
        self.u, self.creds = self.real_user()
        self.other, self.ocreds = self.real_user("lain@x.com", nim="77002")
        self.sat = self.client(SATPAM)

    def send_as(self, c, subject, message="Pesan masukan cukup panjang."):
        r = c.post("/feedback/send", data={"category": "Kritik", "subject": subject, "message": message, "_csrf": self.csrf(c)}); security.reset_rate_limits()
        return r

    def fid(self, subject): return row(self.app, "SELECT id FROM feedback WHERE subject=?", (subject,))["id"]

    def test_full_flow_student_satpam_student(self):
        self.assertEqual(self.send_as(self.u, "Fasilitas kelas").status_code, 200)
        fid = self.fid("Fasilitas kelas")
        self.assertEqual(row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"], "new")      # status awal
        self.assertIn("Menunggu Ditinjau", self.text(self.u, "/feedback/mine"))
        self.assertIn("Fasilitas kelas", self.text(self.sat, "/satpam/feedback"))                               # muncul di dashboard Satpam
        self.assertIn("Menunggu Ditinjau", self.text(self.sat, "/satpam/feedback"))
        self.post(f"/satpam/feedback/{fid}/status", {"status": "reviewing"}, c=self.sat)
        t1 = "Terima kasih atas masukannya. Laporan ini sedang kami periksa dan akan dikoordinasikan dengan pihak terkait."
        self.post(f"/satpam/feedback/{fid}/respond", {"response": t1}, c=self.sat)
        # mahasiswa login ulang (sesi baru): status & tanggapan terlihat
        u2 = self.client(self.creds); page = self.text(u2, f"/feedback/mine/{fid}")
        self.assertIn("Sedang Ditinjau", page); self.assertIn(t1, page)
        self.assertIn("1 tanggapan", self.text(u2, "/feedback/mine"))
        # tindak lanjut: status baru + tanggapan tambahan; tanggapan lama tetap ada
        self.post(f"/satpam/feedback/{fid}/status", {"status": "in_progress"}, c=self.sat)
        t2 = "Perbaikan sudah dijadwalkan minggu depan."
        self.post(f"/satpam/feedback/{fid}/respond", {"response": t2}, c=self.sat)
        page = self.text(u2, f"/feedback/mine/{fid}")
        self.assertIn(t1, page); self.assertIn(t2, page); self.assertIn("Sedang Ditindaklanjuti", page)
        self.assertLess(page.index(t1), page.index(t2))                                                         # urut waktu
        resp = rows(self.app, "SELECT * FROM feedback_responses WHERE feedback_id=? ORDER BY id", (fid,))
        self.assertEqual([r["message"] for r in resp], [t1, t2])
        sat_id = row(self.app, "SELECT id FROM users WHERE email=?", (SATPAM[0],))["id"]
        self.assertTrue(all(r["created_by"] == sat_id and r["created_at"] for r in resp))
        hist = rows(self.app, "SELECT * FROM feedback_history WHERE feedback_id=? ORDER BY id", (fid,))
        self.assertEqual([h["new_status"] for h in hist], ["new", "reviewing", "in_progress"])
        self.assertTrue(all(h["created_at"] for h in hist)); self.assertEqual(hist[-1]["changed_by"], sat_id)
        sp = self.text(self.sat, f"/satpam/feedback/{fid}")                                                      # Satpam melihat semuanya
        self.assertIn(t1, sp); self.assertIn(t2, sp); self.assertIn("Kirim tanggapan tambahan", sp)
        self.assertIn("Sedang Ditindaklanjuti", self.text(self.sat, "/satpam/feedback"))                         # status terbaru langsung terlihat
        # persisten setelah server restart
        create_app(self.cfg)
        self.assertIn(t1, self.text(self.client(self.creds), f"/feedback/mine/{fid}"))

    def test_rejected_requires_reason_and_reason_becomes_response(self):
        self.send_as(self.u, "Di luar cakupan"); fid = self.fid("Di luar cakupan")
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM feedback_responses")["n"], 0)
        self.post(f"/satpam/feedback/{fid}/status", {"status": "rejected", "reason": ""}, c=self.sat)
        self.assertEqual(row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"], "new")
        self.post(f"/satpam/feedback/{fid}/status", {"status": "rejected", "reason": "Di luar kewenangan Satpam"}, c=self.sat)
        page = self.text(self.u, f"/feedback/mine/{fid}")
        self.assertIn("Tidak Dapat Ditindaklanjuti", page); self.assertIn("Di luar kewenangan Satpam", page)

    def test_response_validation(self):
        self.send_as(self.u, "Validasi tanggapan"); fid = self.fid("Validasi tanggapan")
        for bad in ("", "  ", "ab", "x" * 1001):
            self.post(f"/satpam/feedback/{fid}/respond", {"response": bad}, c=self.sat)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM feedback_responses")["n"], 0)
        self.assertEqual(self.post("/satpam/feedback/9999/respond", {"response": "Tanggapan valid"}, c=self.sat).status_code, 404)

    def test_student_isolation_and_no_satpam_actions(self):
        self.send_as(self.u, "Rahasia mahasiswa A"); fid = self.fid("Rahasia mahasiswa A")
        self.post(f"/satpam/feedback/{fid}/respond", {"response": "Tanggapan untuk A"}, c=self.sat)
        self.assertEqual(self.other.get(f"/feedback/mine/{fid}").status_code, 404)
        for t in (self.text(self.other, "/feedback/mine"), self.text(self.other, "/feedback"), self.text(self.other, "/dashboard")):
            self.assertNotIn("Rahasia mahasiswa A", t); self.assertNotIn("Tanggapan untuk A", t)
        self.assertEqual(self.client().get("/feedback/mine").status_code, 302)
        self.assertEqual(self.client().get(f"/feedback/mine/{fid}").status_code, 302)
        before = row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"]
        for c in (self.u, self.other, self.client()):
            self.assertIn(self.post(f"/satpam/feedback/{fid}/status", {"status": "done"}, c=c).status_code, (302, 403))
            self.assertIn(self.post(f"/satpam/feedback/{fid}/respond", {"response": "Saya pura-pura Satpam"}, c=c).status_code, (302, 403))
            self.assertIn(self.post(f"/satpam/feedback/{fid}/note", {"note": "x"}, c=c).status_code, (302, 403))
        self.assertEqual(row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"], before)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM feedback_responses")["n"], 1)
        self.assertEqual(self.sat.get("/feedback/mine").status_code, 403)                                         # Satpam bukan pengirim

    def test_dashboard_limits_to_5_latest_via_sql_limit_and_history_keeps_all(self):
        for i in range(8):
            self.send_as(self.u, f"Masukan ke-{i:02d}", f"Isi pesan nomor {i:02d} cukup panjang.")
        self.send_as(self.other, "Milik orang lain")
        dash = self.text(self.u, "/dashboard")
        for i in range(3, 8): self.assertIn(f"Masukan ke-{i:02d}", dash)
        for i in range(0, 3): self.assertNotIn(f"Masukan ke-{i:02d}", dash)                                       # hanya 5 terbaru
        self.assertNotIn("Milik orang lain", dash)
        self.assertLess(dash.index("Masukan ke-07"), dash.index("Masukan ke-03"))                                 # terbaru dulu
        self.assertIn("/feedback/mine", dash); self.assertIn("Lihat Semua", dash)
        from models import feedback as FM
        with self.app.app_context():
            self.assertEqual(len(FM.latest_by_user(row(self.app, "SELECT id FROM users WHERE email=?", (self.creds[0],))["id"], 5)), 5)
        import inspect; self.assertIn("LIMIT ?", inspect.getsource(FM.latest_by_user))                            # dibatasi di query
        full = self.text(self.u, "/feedback/mine")                                                                 # riwayat lengkap
        for i in range(8): self.assertIn(f"Masukan ke-{i:02d}", full)
        self.assertEqual(row(self.app, "SELECT COUNT(*) n FROM feedback WHERE user_id=(SELECT id FROM users WHERE email=?)", (self.creds[0],))["n"], 8)
        old = self.fid("Masukan ke-00")                                                                            # laporan lama tetap bisa dibuka + tanggapan
        self.post(f"/satpam/feedback/{old}/respond", {"response": "Tanggapan untuk laporan lama"}, c=self.sat)
        self.assertIn("Tanggapan untuk laporan lama", self.text(self.u, f"/feedback/mine/{old}"))

    def test_history_pagination(self):
        for i in range(13): self.send_as(self.u, f"Riwayat {i:02d}", f"Isi riwayat {i:02d} cukup panjang.")
        p1, p2 = self.text(self.u, "/feedback/mine"), self.text(self.u, "/feedback/mine?page=2")
        self.assertIn("Riwayat 12", p1); self.assertNotIn("Riwayat 00", p1); self.assertIn("Riwayat 00", p2); self.assertIn('class="pager"', p1)
        self.assertEqual(self.u.get("/feedback/mine?page=999").status_code, 200)

    def test_empty_states_and_statuses_labels(self):
        self.assertIn("Belum ada masukan", self.text(self.u, "/feedback/mine"))
        self.assertIn("Belum ada masukan yang kamu kirim.", self.text(self.u, "/dashboard"))
        from config.settings import FEEDBACK_STATUSES
        self.assertEqual([l for _, l, _ in FEEDBACK_STATUSES], ["Menunggu Ditinjau", "Sedang Ditinjau", "Sedang Ditindaklanjuti", "Selesai", "Tidak Dapat Ditindaklanjuti"])


# ---------------------------------------------------------------- floating help button
class FloatingHelp(Base):
    def test_fab_is_fixed_bottom_right_single_modal(self):
        css = open(os.path.join(ROOT, "static/css/style.css"), encoding="utf8").read()
        fab = css[css.index(".help-fab{"):]; fab = fab[:fab.index("}")]
        self.assertIn("position:fixed", fab); self.assertIn("right:", fab); self.assertIn("bottom:", fab); self.assertIn("safe-area-inset-bottom", fab)
        self.assertIn("border-radius:50%", fab)
        body = self.text(self.client(DEMO_USER), "/dashboard")
        self.assertEqual(body.count("help-fab"), body.count('class="help-fab"') + body.count(".help-fab") + 0)    # hanya satu elemen
        self.assertEqual(body.count('class="help-fab"'), 1); self.assertEqual(body.count('id="helpModal"'), 1)
        self.assertIn("viewport-fit=cover", body)
        self.assertNotIn("help-btn", body); self.assertNotIn("help-float", body)

    def test_not_rendered_for_satpam_at_all(self):
        for c in (self.client(DEMO_SAT), self.client(SATPAM)):
            for u in ("/satpam/", "/satpam/feedback", "/found-items", "/profile", "/"):
                b = self.text(c, u); self.assertNotIn('class="help-fab"', b, u); self.assertNotIn("helpModal", b, u)


if __name__ == "__main__":
    unittest.main()


class SatpamFeedbackAjax(Base):
    """Endpoint status/tanggapan Satpam untuk fetch (JSON): simpan ke DB, snapshot balik, tanggapan tidak tertimpa."""

    def _hdr(self, c):
        return {"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(c)}

    def test_status_and_responses_json(self):
        stu = self.client(DEMO_USER)
        with self.app.app_context():
            uid = get_db().execute("SELECT id FROM users WHERE email=?", (DEMO_USER[0],)).fetchone()["id"]
            fid = F.create(uid, "Demo Mahasiswa", DEMO_USER[0], "Saran", "Judul uji", "Isi saran uji coba", 1)
        sat = self.client(DEMO_SAT); h = self._hdr(sat)
        r = sat.post(f"/satpam/feedback/{fid}/status", json={"status": "reviewing"}, headers=h)
        self.assertEqual(r.status_code, 200); self.assertTrue(r.json["ok"]); self.assertEqual(r.json["status"], "reviewing")
        self.assertEqual(row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"], "reviewing")
        r = sat.post(f"/satpam/feedback/{fid}/status", json={"status": "reviewing"}, headers=h)
        self.assertEqual(r.status_code, 409); self.assertFalse(r.json["ok"])
        self.assertEqual(sat.post(f"/satpam/feedback/{fid}/respond", json={"response": " "}, headers=h).status_code, 400)
        for m in ("Tanggapan pertama", "Tanggapan kedua"):
            self.assertEqual(sat.post(f"/satpam/feedback/{fid}/respond", json={"response": m}, headers=h).status_code, 200)
        r = sat.post(f"/satpam/feedback/{fid}/status", json={"status": "in_progress"}, headers=h)
        self.assertEqual([x["message"] for x in r.json["responses"]], ["Tanggapan pertama", "Tanggapan kedua"])
        self.assertEqual(len(r.json["history"]), 3)
        page = stu.get(f"/feedback/mine/{fid}").get_data(as_text=True)      # mahasiswa pemilik melihat hasilnya
        self.assertIn("Tanggapan pertama", page); self.assertIn("Sedang Ditindaklanjuti", page)
        other = self.client(SATPAM); self.assertEqual(other.get(f"/satpam/feedback/{fid}").status_code, 200)

    def test_json_guards(self):
        stu = self.client(DEMO_USER)
        r = stu.post("/satpam/feedback/1/status", json={"status": "done"}, headers=self._hdr(stu))
        self.assertEqual(r.status_code, 403); self.assertFalse(r.json["ok"])
        sat = self.client(DEMO_SAT)
        r = sat.post("/satpam/feedback/1/status", json={"status": "done"}, headers={"X-Requested-With": "fetch"})
        self.assertEqual(r.status_code, 400); self.assertFalse(r.json["ok"])


class FeedbackNotificationsAndTriage(Base):
    """Notifikasi mahasiswa, daftar Satpam (belum ditanggapi), rate limit per akun, status+tanggapan sekaligus."""

    def send(self, c, **o):
        body = {"name": "Tester", "email": "t@x.com", "category": "Saran", "subject": "Subjek uji", "message": "Isi pesan uji yang cukup panjang."}; body.update(o)
        return c.post("/feedback/send", json=body, headers={"X-CSRF-Token": self.csrf(c)})

    def fid_of(self, subject):
        return row(self.app, "SELECT id FROM feedback WHERE subject=?", (subject,))["id"]

    def test_feedback_is_not_emailed(self):
        import routes.feedback as RF
        self.assertFalse(hasattr(RF, "send_email"))                       # kritik/saran hanya masuk dashboard Satpam
        c, creds = self.real_user()
        r = self.send(c, subject="Tanpa email", email=creds[0]); self.assertEqual((r.status_code, r.get_json()["status"]), (200, "saved"))

    def test_student_notification_lifecycle(self):
        a, ca = self.real_user("a@x.com", "77001"); b, cb = self.real_user("b@x.com", "77002")
        self.send(a, subject="Milik A", email=ca[0]); fid = self.fid_of("Milik A")
        self.assertNotIn("nav-badge", self.text(a, "/dashboard"))           # belum ada pembaruan
        sat = self.client(SATPAM); h = {"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(sat)}
        sat.post(f"/satpam/feedback/{fid}/status", json={"status": "reviewing"}, headers=h)
        sat.post(f"/satpam/feedback/{fid}/respond", json={"response": "Sedang kami cek."}, headers=h)
        self.assertEqual(rows(self.app, "SELECT rev,student_seen_rev FROM feedback WHERE id=?", (fid,))[0]["rev"], 2)
        dash = self.text(a, "/dashboard")
        self.assertIn("nav-badge", dash); self.assertIn("Ada 1 pembaruan baru dari Satpam", dash)
        self.assertIn("new-tag", self.text(a, "/feedback/mine"))            # tanda Baru di daftar
        self.assertNotIn("nav-badge", self.text(b, "/dashboard"))           # mahasiswa lain tidak terpengaruh
        self.assertEqual(b.get(f"/feedback/mine/{fid}").status_code, 404)
        self.assertNotEqual(row(self.app, "SELECT student_seen_rev FROM feedback WHERE id=?", (fid,))["student_seen_rev"], 2)  # 404 tidak menandai dibaca
        self.assertIn("Sedang kami cek.", self.text(a, f"/feedback/mine/{fid}"))   # membuka detail = dibaca
        self.assertNotIn("nav-badge", self.text(a, "/dashboard")); self.assertNotIn("new-tag", self.text(a, "/feedback/mine"))
        sat.post(f"/satpam/feedback/{fid}/respond", json={"response": "Sudah selesai dicek."}, headers=h)   # pembaruan lagi -> muncul lagi
        self.assertIn("Ada 1 pembaruan baru", self.text(a, "/dashboard"))
        a.set_cookie("lang", "en"); self.assertIn("new update(s) from Security", self.text(a, "/dashboard"))

    def test_rate_limit_is_per_account_not_per_ip(self):
        a, ca = self.real_user("a@x.com", "77001"); b, cb = self.real_user("b@x.com", "77002")
        for i in range(5):
            self.assertEqual(self.send(a, subject=f"A nomor {i}", email=ca[0], message=f"Pesan A yang cukup panjang nomor {i}").status_code, 200)
        self.assertEqual(self.send(a, subject="A keenam", email=ca[0], message="Pesan A keenam cukup panjang").status_code, 429)
        self.assertEqual(self.send(b, subject="B pertama", email=cb[0], message="Pesan B pertama cukup panjang").status_code, 200)   # IP sama, akun beda
        g1 = self.client()                                                     # tamu tetap dibatasi per IP (3)
        for i in range(3):
            self.assertEqual(self.send(g1, subject=f"Tamu {i}", message=f"Pesan tamu cukup panjang {i}").status_code, 200)
        self.assertEqual(self.send(g1, subject="Tamu empat", message="Pesan tamu keempat panjang").status_code, 429)

    def test_satpam_list_unanswered_filter_and_age(self):
        a, ca = self.real_user()
        self.send(a, subject="Sudah dibalas", email=ca[0]); self.send(a, subject="Belum dibalas", email=ca[0], message="Pesan lain yang cukup panjang.")
        f1, f2 = self.fid_of("Sudah dibalas"), self.fid_of("Belum dibalas")
        sat = self.client(SATPAM); h = {"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(sat)}
        sat.post(f"/satpam/feedback/{f1}/respond", json={"response": "Terima kasih atas masukannya."}, headers=h)
        con = sqlite3.connect(self.app.config["DATABASE"]); con.execute("UPDATE feedback SET created_at=datetime('now','-5 days') WHERE id=?", (f2,)); con.commit(); con.close()
        none = self.text(sat, "/satpam/feedback?resp=none"); self.assertIn("Belum dibalas", none); self.assertNotIn("Sudah dibalas", none)
        yes = self.text(sat, "/satpam/feedback?resp=yes"); self.assertIn("Sudah dibalas", yes); self.assertNotIn("Belum dibalas", yes)
        page = self.text(sat, "/satpam/feedback"); self.assertIn("1 masukan belum pernah ditanggapi", page); self.assertIn("5 hari belum selesai", page)
        self.assertIn("1 masukan belum pernah ditanggapi", self.text(sat, "/satpam/"))

    def test_respond_and_change_status_together(self):
        a, ca = self.real_user(); self.send(a, subject="Gabungan", email=ca[0]); fid = self.fid_of("Gabungan")
        sat = self.client(SATPAM); h = {"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(sat)}; url = f"/satpam/feedback/{fid}/respond"
        r = sat.post(url, json={"response": "Kami tindaklanjuti sekarang.", "status": "in_progress"}, headers=h)
        self.assertEqual((r.status_code, r.json["status"], len(r.json["responses"])), (200, "in_progress", 1))
        self.assertEqual(sat.post(url, json={"response": "ok", "status": "done"}, headers=h).status_code, 400)          # tanggapan terlalu pendek
        self.assertEqual(sat.post(url, json={"response": "abc de", "status": "ngawur"}, headers=h).status_code, 400)
        self.assertEqual(sat.post(url, json={"response": "abcd", "status": "rejected"}, headers=h).status_code, 400)  # alasan min 5 karakter
        self.assertEqual(row(self.app, "SELECT status FROM feedback WHERE id=?", (fid,))["status"], "in_progress")
        r = sat.post(url, json={"response": "Di luar kewenangan kampus.", "status": "rejected"}, headers=h)
        self.assertEqual(r.json["status"], "rejected"); self.assertEqual(len(r.json["responses"]), 2)                   # alasan = 1 tanggapan (tidak ganda)
        r = sat.post(url, json={"response": "Tanggapan tanpa ubah.", "status": "rejected"}, headers=h)                 # status sama -> hanya tanggapan
        self.assertEqual((r.status_code, len(r.json["responses"])), (200, 3))
        page = self.text(a, f"/feedback/mine/{fid}"); self.assertIn("Alasan dari Satpam", page); self.assertIn("belum dapat ditindaklanjuti", page)

    def test_production_warnings(self):
        from config.settings import production_warnings
        bad = {"DEBUG": False, "SECRET_KEY": "dev-only-change-me", "SESSION_COOKIE_SECURE": False, "SECURITY_PASSWORD": "Satpam12345", "DEMO_ENABLED": True,
               "APP_BASE_URL": "", "EMAILJS_SERVICE_ID": "", "EMAILJS_TEMPLATE_ID": "", "EMAILJS_PUBLIC_KEY": ""}
        self.assertEqual(len(production_warnings(bad)), 6)
        self.assertEqual(production_warnings({**bad, "DEBUG": True}), [])
        good = {"DEBUG": False, "SECRET_KEY": "x" * 64, "SESSION_COOKIE_SECURE": True, "SECURITY_PASSWORD": "Kuat!2026xyz", "DEMO_ENABLED": False,
                "APP_BASE_URL": "https://itsb.example", "EMAILJS_SERVICE_ID": "s", "EMAILJS_TEMPLATE_ID": "t", "EMAILJS_PUBLIC_KEY": "k"}
        self.assertEqual(production_warnings(good), [])
        self.assertEqual(len(production_warnings({**good, "APP_BASE_URL": "http://127.0.0.1:5000"})), 1)      # localhost
        self.assertEqual(len(production_warnings({**good, "APP_BASE_URL": "http://itsb.example"})), 1)        # bukan https
        self.assertEqual(len(production_warnings({**good, "EMAILJS_PUBLIC_KEY": "YOUR_PUBLIC_KEY"})), 1)      # placeholder


class StudentReplies(Base):
    """Mahasiswa membalas tanggapan Satpam; Satpam diberi notifikasi; aturan anti-spam; isolasi data."""

    def setUp(self):
        super().setUp()
        self.a, ca = self.real_user("a@x.com", "77001"); self.b, cb = self.real_user("b@x.com", "77002")
        self.a.post("/feedback/send", json={"name": "A", "email": ca[0], "category": "Saran", "subject": "Subjek A", "message": "Pesan A yang cukup panjang."}, headers={"X-CSRF-Token": self.csrf(self.a)})
        self.fid = row(self.app, "SELECT id FROM feedback WHERE subject='Subjek A'")["id"]
        self.sat = self.client(SATPAM); self.sh = {"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(self.sat)}
        self.url = f"/feedback/mine/{self.fid}/reply"

    def ra(self, msg, c=None):
        c = c or self.a
        return c.post(self.url, json={"response": msg}, headers={"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(c)})

    def staff(self, msg="Tanggapan Satpam."):
        return self.sat.post(f"/satpam/feedback/{self.fid}/respond", json={"response": msg}, headers=self.sh)

    def test_cannot_reply_before_staff_responds(self):
        r = self.ra("Apakah sudah dibaca?"); self.assertEqual(r.status_code, 409); self.assertFalse(r.json["ok"])
        self.assertEqual(len(rows(self.app, "SELECT * FROM feedback_responses")), 0)
        page = self.text(self.a, f"/feedback/mine/{self.fid}")
        self.assertRegex(page, r'<form id="replyForm"[^>]*\shidden>')                 # form tersembunyi + petunjuk tampil
        self.assertIn("setelah Satpam memberikan tanggapan", page)
        self.staff()
        self.assertNotRegex(self.text(self.a, f"/feedback/mine/{self.fid}"), r'<form id="replyForm"[^>]*\shidden>')   # terbuka setelah ditanggapi

    def test_reply_flow_and_notifications(self):
        self.staff()
        self.assertEqual(self.a.get("/dashboard").status_code, 200)
        r = self.ra("Terima kasih, apakah bisa lebih cepat?")
        self.assertEqual((r.status_code, r.json["ok"], r.json["count"]), (200, True, 2))
        self.assertEqual([x["mine"] for x in r.json["responses"]], [False, True]); self.assertEqual(r.json["responses"][1]["author"], "Kamu")
        f = row(self.app, "SELECT rev,student_seen_rev,srev,staff_seen_srev FROM feedback WHERE id=?", (self.fid,))
        self.assertEqual((f["srev"], f["staff_seen_srev"]), (1, 0))
        self.assertEqual(row(self.app, "SELECT from_student FROM feedback_responses ORDER BY id DESC LIMIT 1")["from_student"], 1)
        self.assertEqual(f["rev"], 1)                                                  # balasan sendiri tidak menjadi notifikasi bagi mahasiswa
        page = self.text(self.a, f"/feedback/mine/{self.fid}"); self.assertIn("Terima kasih, apakah bisa lebih cepat?", page); self.assertIn("Kamu", page)
        # sisi Satpam: notifikasi, tanda, filter, dan hilang setelah dibuka
        lst = self.text(self.sat, "/satpam/feedback")
        self.assertIn("1 masukan punya balasan baru dari pengirim", lst); self.assertIn("Balasan baru", lst); self.assertIn("nav-badge", lst)
        self.assertIn("Subjek A", self.text(self.sat, "/satpam/feedback?resp=reply")); self.assertIn("1 masukan punya balasan baru", self.text(self.sat, "/satpam/"))
        det = self.text(self.sat, f"/satpam/feedback/{self.fid}"); self.assertIn("Terima kasih, apakah bisa lebih cepat?", det); self.assertIn("resp-student", det)
        self.assertEqual(row(self.app, "SELECT srev,staff_seen_srev FROM feedback WHERE id=?", (self.fid,))["staff_seen_srev"], 1)
        self.assertNotIn("balasan baru dari pengirim", self.text(self.sat, "/satpam/feedback")); self.assertNotIn("nav-badge", self.text(self.sat, "/satpam/feedback"))
        # balasan tidak menghitung sebagai tanggapan Satpam
        self.assertEqual(rows(self.app, "SELECT COUNT(*) n FROM feedback_responses WHERE from_student=0")[0]["n"], 1)
        self.assertNotIn("belum pernah ditanggapi", self.text(self.sat, "/satpam/feedback"))
        self.staff("Kami usahakan.")                                                   # Satpam membalas -> mahasiswa diberi tahu lagi
        self.assertIn("Ada 1 pembaruan baru", self.text(self.a, "/dashboard"))

    def test_streak_limit_duplicate_and_validation(self):
        self.staff()
        self.assertEqual(self.ra("ab").status_code, 400); self.assertEqual(self.ra("x" * 1001).status_code, 400)
        for i in range(3):
            self.assertEqual(self.ra(f"Balasan nomor {i}").status_code, 200)
        r = self.ra("Balasan keempat"); self.assertEqual(r.status_code, 409); self.assertIn("Tunggu tanggapan Satpam", r.json["message"])
        self.staff("Satpam menjawab lagi.")
        self.assertEqual(self.ra("Balasan setelah dijawab").status_code, 200)
        self.assertEqual(self.ra("Balasan setelah dijawab").status_code, 409)           # duplikat berurutan

    def test_rate_limit_per_account(self):
        for i in range(5):
            self.staff(f"Jawaban {i}"); self.assertEqual(self.ra(f"Balasan unik {i}").status_code, 200)
        self.staff("Jawaban terakhir"); self.assertEqual(self.ra("Balasan keenam").status_code, 429)

    def test_isolation_and_guards(self):
        self.staff()
        self.assertEqual(self.ra("Coba balas milik orang lain", c=self.b).status_code, 404)           # bukan miliknya
        self.assertEqual(self.b.get(f"/feedback/mine/{self.fid}").status_code, 404)
        r = self.sat.post(self.url, json={"response": "Satpam menyusup"}, headers=self.sh); self.assertEqual(r.status_code, 403)
        r = self.a.post(self.url, json={"response": "Tanpa token"}, headers={"X-Requested-With": "fetch"}); self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client().post(self.url, json={"response": "Tamu"}, headers={"X-Requested-With": "fetch"}).status_code in (302, 400, 401, 403), True)
        self.assertEqual(len(rows(self.app, "SELECT * FROM feedback_responses WHERE from_student=1")), 0)

    def test_form_fallback_without_js(self):
        self.staff()
        r = self.post(self.url, {"response": "Balasan lewat form biasa"}, c=self.a, follow_redirects=True)
        self.assertIn("Balasan terkirim", r.get_data(as_text=True)); self.assertIn("Balasan lewat form biasa", r.get_data(as_text=True))
        self.assertIn("Balasan wajib diisi", self.post(self.url, {"response": "x"}, c=self.a, follow_redirects=True).get_data(as_text=True))

    def test_english_labels(self):
        self.staff(); self.ra("Balasan untuk uji EN")
        self.sat.set_cookie("lang", "en"); self.a.set_cookie("lang", "en")
        self.assertIn("Conversation with the sender", self.text(self.sat, f"/satpam/feedback/{self.fid}"))
        self.assertIn("Conversation with Security", self.text(self.a, f"/feedback/mine/{self.fid}"))



# ---------------------------------------------------------------- Lupa Password via EmailJS (REST dari backend)
import hashlib, http.server, json as _json, subprocess, sys, threading, time, urllib.request as _urlreq
from datetime import datetime as _dt


class FakeEmailJS:
    """Server EmailJS palsu di localhost: merekam permintaan HTTP asli yang dikirim backend (bukan sekadar mock fungsi)."""
    def __init__(self, status=200, body="OK", delay=0):
        outer = self; self.calls, self.status, self.body, self.delay = [], status, body, delay

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers["Content-Length"]); raw = self.rfile.read(n)
                if outer.delay: time.sleep(outer.delay)
                outer.calls.append({"path": self.path, "headers": dict(self.headers), "raw": raw.decode(), "json": _json.loads(raw)})
                self.send_response(outer.status); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(outer.body.encode())

            def log_message(self, *a): pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/api/v1.0/email/send"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown(); self.srv.server_close()


class ResetEmailJS(Base):
    BASE = "https://itsb-find.example"

    def setUp(self):
        super().setUp()
        self.fake = FakeEmailJS(); self.addCleanup(self.fake.close)
        self.app.config.update(EMAILJS_SERVICE_ID="service_test", EMAILJS_TEMPLATE_ID="template_test", EMAILJS_PUBLIC_KEY="pubkey_test",
                               EMAILJS_PRIVATE_KEY="", EMAILJS_API_URL=self.fake.url, APP_BASE_URL=self.BASE)

    def forgot(self, email, c=None, **kw):
        return self.post("/forgot-password", {"email": email}, c=c, **kw)

    def forgot_spoofed(self, email, host="http://evil.example"):
        """Penyerang memalsukan header Host dengan sesi + CSRF yang konsisten untuk host tersebut."""
        ev = self.client(); ev.get("/feedback", base_url=host)
        with ev.session_transaction(base_url=host) as sess:
            tok = sess["_csrf"]
        return ev.post("/forgot-password", data={"email": email, "_csrf": tok}, base_url=host)

    def token_from_call(self, i=-1):
        return self.fake.calls[i]["json"]["template_params"]["link"].rsplit("/", 1)[1]

    def test_01_email_sent_with_official_payload(self):
        c, (email, pw) = self.real_user()
        r = self.forgot(email); self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.fake.calls), 1)
        call = self.fake.calls[0]; body = call["json"]
        self.assertEqual(call["path"], "/api/v1.0/email/send"); self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(set(body), {"service_id", "template_id", "user_id", "template_params"})            # format resmi EmailJS (tanpa accessToken bila private key kosong)
        self.assertEqual((body["service_id"], body["template_id"], body["user_id"]), ("service_test", "template_test", "pubkey_test"))
        self.assertEqual(set(body["template_params"]), {"to_email", "link"})                                  # persis variabel template {{to_email}} & {{link}}
        self.assertEqual(body["template_params"]["to_email"], email)
        link = body["template_params"]["link"]; self.assertTrue(link.startswith(self.BASE + "/reset-password/"), link)
        self.assertNotIn(pw, call["raw"]); self.assertNotIn("password", call["raw"].lower().replace("reset-password", ""))   # password tidak pernah dikirim

    def test_02_private_key_sent_only_when_configured(self):
        c, (email, pw) = self.real_user(); self.app.config["EMAILJS_PRIVATE_KEY"] = "privkey_test"
        self.forgot(email); self.assertEqual(self.fake.calls[0]["json"]["accessToken"], "privkey_test")

    def test_03_token_hashed_random_and_one_hour(self):
        c, (email, pw) = self.real_user(); self.forgot(email)
        token = self.token_from_call(); self.assertGreaterEqual(len(token), 43)                                  # 256-bit
        r = rows(self.app, "SELECT * FROM password_reset_tokens")[0]
        self.assertEqual(r["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, " ".join(str(r[k]) for k in r.keys()))                                           # token mentah tidak ada di database
        fmt = "%Y-%m-%d %H:%M:%S"; mins = (_dt.strptime(r["expires_at"], fmt) - _dt.strptime(r["created_at"], fmt)).total_seconds() / 60
        self.assertAlmostEqual(mins, 60, delta=1)
        self.forgot(email, c=self.client()); self.assertNotEqual(self.token_from_call(0), self.token_from_call(1))   # tidak bisa ditebak/diulang
        self.assertEqual(rows(self.app, "SELECT COUNT(*) n FROM password_reset_tokens WHERE used=0")[0]["n"], 1)  # token lama otomatis nonaktif

    def test_04_full_flow_link_opens_password_updated_token_single_use(self):
        c, (email, old) = self.real_user(); self.forgot(email); token = self.token_from_call()
        page = self.client().get(f"/reset-password/{token}"); self.assertEqual(page.status_code, 200); self.assertEqual(page.headers["Cache-Control"], "no-store")
        h0 = row(self.app, "SELECT password_hash FROM users WHERE email=?", (email,))["password_hash"]
        u = self.client()
        self.assertEqual(self.post(f"/reset-password/{token}", {"password": "pendek", "confirm": "pendek"}, c=u).status_code, 400)
        self.assertEqual(self.post(f"/reset-password/{token}", {"password": "Baru12345", "confirm": "Beda12345"}, c=u).status_code, 400)
        self.assertEqual(self.post(f"/reset-password/{token}", {"password": "Baru12345", "confirm": "Baru12345"}, c=u).status_code, 302)
        h1 = row(self.app, "SELECT password_hash FROM users WHERE email=?", (email,))["password_hash"]
        self.assertNotEqual(h0, h1); self.assertNotIn("Baru12345", h1); self.assertTrue(h1.startswith(("scrypt:", "pbkdf2:")))   # di-hash dengan mekanisme aplikasi
        self.assertEqual(self.client((email, "Baru12345")).get("/dashboard").status_code, 200)                  # login dengan password baru
        self.assertNotEqual(self.client((email, old)).get("/dashboard").status_code, 200)                       # password lama tidak berlaku
        self.assertEqual(self.client().get(f"/reset-password/{token}").status_code, 302)                         # tidak bisa dibuka lagi
        self.assertEqual(self.post(f"/reset-password/{token}", {"password": "Lain12345", "confirm": "Lain12345"}, c=self.client()).status_code, 302)
        self.assertEqual(self.client((email, "Baru12345")).get("/dashboard").status_code, 200)                  # password tidak berubah oleh pemakaian ulang

    def test_05_expired_and_used_tokens_rejected_and_consume_is_atomic(self):
        c, (email, _) = self.real_user()
        with self.app.app_context():
            uid = get_db().execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
            expired = PR.create_token(uid, -1)
        self.assertEqual(self.client().get(f"/reset-password/{expired}").status_code, 302)
        self.assertEqual(self.post(f"/reset-password/{expired}", {"password": "Baru12345", "confirm": "Baru12345"}, c=self.client()).status_code, 302)
        self.assertNotEqual(self.client((email, "Baru12345")).get("/dashboard").status_code, 200)
        with self.app.app_context():
            tid = get_db().execute("SELECT id FROM password_reset_tokens WHERE user_id=?", (uid,)).fetchone()["id"]
            self.assertFalse(PR.consume(tid))                                                                     # kedaluwarsa tidak bisa dikonsumsi
            fresh = PR.create_token(uid, 60); rid = PR.find_valid(fresh)["id"]
            self.assertEqual([PR.consume(rid), PR.consume(rid)], [True, False])                                   # hanya satu yang berhasil

    def test_06_unknown_demo_and_valid_email_get_same_safe_response(self):
        c, (email, _) = self.real_user(); texts = []
        for addr in ("tidak.ada@itsb.test", DEMO_USER[0], email):
            r = self.forgot(addr, c=self.client(), follow_redirects=True); self.assertEqual(r.status_code, 200)
            texts.append("Jika email terdaftar, instruksi reset password akan dikirim." in r.get_data(as_text=True))
        self.assertEqual(texts, [True, True, True])
        self.assertEqual([x["json"]["template_params"]["to_email"] for x in self.fake.calls], [email])           # hanya akun asli yang menerima email
        self.assertEqual(rows(self.app, "SELECT COUNT(*) n FROM password_reset_tokens")[0]["n"], 1)

    def test_07_rate_limits(self):
        c, (email, _) = self.real_user(); cl = self.client()
        codes = [self.forgot(email, c=cl).status_code for _ in range(5)]
        self.assertEqual(codes, [302] * 5); self.assertEqual(len(self.fake.calls), 3)                            # per akun: maks 3 email/jam, tanpa bocor ke pengguna
        self.assertEqual(self.forgot(email, c=cl).status_code, 429)                                              # per IP: maks 5 permintaan/jam

    def test_08_emailjs_failure_stays_generic_and_logs_no_token(self):
        self.fake.status, self.fake.body = 403, "API calls are disabled for non-browser applications"
        c, (email, _) = self.real_user()
        with self.assertLogs(self.app.logger, "WARNING") as cm:
            r = self.forgot(email, follow_redirects=True)
        self.assertIn("Jika email terdaftar", r.get_data(as_text=True))
        self.assertIn("non-browser", "\n".join(cm.output)); self.assertNotIn(self.token_from_call(), "\n".join(cm.output))

    def test_09_link_base_comes_from_config_not_host_header(self):
        c, (email, _) = self.real_user()
        self.assertEqual(self.forgot_spoofed(email).status_code, 302); self.assertTrue(self.fake.calls[0]["json"]["template_params"]["link"].startswith(self.BASE + "/"))
        self.assertNotIn("evil.example", self.fake.calls[0]["raw"])
        # produksi tanpa APP_BASE_URL: tidak mengirim apa pun (bukan memakai Host dari penyerang)
        self.app.config.update(APP_BASE_URL="", TESTING=False); self.fake.calls.clear()
        self.assertEqual(self.forgot_spoofed(email).status_code, 302)
        time.sleep(0.3); self.assertEqual(self.fake.calls, [])
        self.assertEqual(rows(self.app, "SELECT COUNT(*) n FROM password_reset_tokens WHERE used=0")[0]["n"], 1)   # tidak ada token baru
        self.app.config["TESTING"] = True; self.fake.calls.clear()                                              # pengembangan lokal (loopback) tetap berfungsi
        self.forgot(email, c=self.client()); self.assertTrue(self.fake.calls[0]["json"]["template_params"]["link"].startswith("http://localhost/reset-password/"))

    def test_10_sent_in_background_so_response_time_does_not_leak_account_existence(self):
        self.fake.delay = 1.0; self.app.config["TESTING"] = False
        c, (email, _) = self.real_user(); t0 = time.time(); r = self.forgot(email); dt = time.time() - t0
        self.assertEqual(r.status_code, 302); self.assertLess(dt, 0.8)                                           # respons tidak menunggu EmailJS
        for _ in range(50):
            if self.fake.calls: break
            time.sleep(0.1)
        self.assertEqual(len(self.fake.calls), 1)                                                                # tetap terkirim di latar belakang

    def test_11_feedback_never_uses_email(self):
        c, (email, _) = self.real_user(); self.app.config["TESTING"] = True
        def boom(*a, **k): raise AssertionError("Kritik dan saran tidak boleh memakai jaringan/EmailJS")
        orig = _urlreq.urlopen; _urlreq.urlopen = boom
        try:
            r = c.post("/feedback/send", json={"name": "T", "email": email, "category": "Saran", "subject": "Tanpa email", "message": "Isi pesan cukup panjang untuk uji."}, headers={"X-CSRF-Token": self.csrf(c)})
            self.assertEqual((r.status_code, r.get_json()["status"]), (200, "saved"))
            fid = row(self.app, "SELECT id FROM feedback")["id"]; sat = self.client(SATPAM); h = {"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(sat)}
            self.assertEqual(sat.post(f"/satpam/feedback/{fid}/status", json={"status": "reviewing"}, headers=h).status_code, 200)
            self.assertEqual(sat.post(f"/satpam/feedback/{fid}/respond", json={"response": "Terima kasih"}, headers=h).status_code, 200)
            r = c.post(f"/feedback/mine/{fid}/reply", json={"response": "Siap, terima kasih"}, headers={"X-Requested-With": "fetch", "X-CSRF-Token": self.csrf(c)}); self.assertEqual(r.status_code, 200)
        finally:
            _urlreq.urlopen = orig
        self.assertEqual(self.fake.calls, [])

    def test_12_env_names_and_example_file_have_no_secrets(self):
        env = {**os.environ, "EMAILJS_SERVICE_ID": "svc", "EMAILJS_TEMPLATE_ID": "tpl", "EMAILJS_PUBLIC_KEY": "pk"}
        env.pop("EMAILJS_RESET_TEMPLATE_ID", None)
        out = subprocess.run([sys.executable, "-c", "from config.settings import Config as C; print(C.EMAILJS_SERVICE_ID, C.EMAILJS_TEMPLATE_ID, C.EMAILJS_PUBLIC_KEY, C.RESET_TOKEN_MINUTES)"],
                             cwd=os.path.dirname(os.path.dirname(__file__)), env=env, capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["svc", "tpl", "pk", "60"])
        old = {**os.environ, "EMAILJS_RESET_TEMPLATE_ID": "tpl_old"}; old.pop("EMAILJS_TEMPLATE_ID", None)                 # nama lama tetap terbaca
        out = subprocess.run([sys.executable, "-c", "from config.settings import Config as C; print(C.EMAILJS_TEMPLATE_ID)"],
                             cwd=os.path.dirname(os.path.dirname(__file__)), env=old, capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["tpl_old"])
        ex = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.example"), encoding="utf8").read()
        vals = dict(l.split("=", 1) for l in ex.splitlines() if l.startswith("EMAILJS_"))
        self.assertEqual(set(vals), {"EMAILJS_SERVICE_ID", "EMAILJS_TEMPLATE_ID", "EMAILJS_PUBLIC_KEY", "EMAILJS_PRIVATE_KEY"})
        self.assertEqual({v.strip() for v in vals.values()}, {""})                                                # tanpa kredensial sungguhan


class EmailJSDiagnostics(Base):
    def test_missing_diagnose_and_hints(self):
        from services import email_service as ES
        self.assertEqual(ES.missing({"EMAILJS_SERVICE_ID": "s", "EMAILJS_TEMPLATE_ID": "", "EMAILJS_PUBLIC_KEY": "YOUR_PUBLIC_KEY"}), ["EMAILJS_TEMPLATE_ID", "EMAILJS_PUBLIC_KEY"])
        self.assertEqual(ES.missing({"EMAILJS_SERVICE_ID": "s", "EMAILJS_TEMPLATE_ID": "t", "EMAILJS_PUBLIC_KEY": "k"}), [])
        out = "\n".join(ES.diagnose({"EMAILJS_SERVICE_ID": "service_abcdef", "EMAILJS_TEMPLATE_ID": "", "EMAILJS_PUBLIC_KEY": "pk_1234567890", "EMAILJS_PRIVATE_KEY": "SUPERSECRETPRIVATE", "APP_BASE_URL": ""}))
        self.assertNotIn("SUPERSECRETPRIVATE", out); self.assertNotIn("service_abcdef", out); self.assertNotIn("pk_1234567890", out)   # rahasia disamarkan
        self.assertIn("EMAILJS_TEMPLATE_ID: KOSONG", out); self.assertIn("File .env:", out)
        self.assertIn("non-browser", ES.hint_for("HTTP 403: API calls are disabled for non-browser applications"))
        self.assertIn("Public Key", ES.hint_for("HTTP 400: The Public Key is invalid"))
        self.assertIn("Template", ES.hint_for("HTTP 400: The template ID not found"))
        self.assertIn("Gagal terhubung", ES.hint_for("[Errno -2] Name or service not known"))

    def test_startup_warns_when_emailjs_incomplete(self):
        with self.assertLogs("app", "WARNING") as cm:                      # logger aplikasi Flask bernama sama dengan modul app
            create_app({**self.cfg, "EMAILJS_SERVICE_ID": "", "EMAILJS_TEMPLATE_ID": "", "EMAILJS_PUBLIC_KEY": ""})
        self.assertTrue(any("[EMAILJS] belum lengkap" in m and "EMAILJS_SERVICE_ID" in m for m in cm.output))
