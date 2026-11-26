# ITSB FIND — Lost & Found Kampus ITSB
Flask + SQLite + Pillow + EmailJS. Proyek tugas kelompok, Institut Teknologi Sains Bandung.

## 0a. Revisi lanjutan (responsif, kritik dan saran, FAB bantuan)
- **Responsif:** tabel otomatis menjadi kartu bertumpuk di layar ≤700px (label diisi `main.js` dari `<th>`), tab filter menjadi baris yang bisa digeser, target sentuh ≥40px, input 16px di HP, modal selalu muat layar (`100dvh` + safe-area), dan di layar ≥1700px konten dibatasi lebarnya. Diaudit di 320/360/390/768/1024/1440/1920px pada 30 halaman: 0 overflow horizontal.
- **Kritik dan saran terintegrasi:** status baru **Menunggu Ditinjau → Sedang Ditinjau → Sedang Ditindaklanjuti → Selesai / Tidak Dapat Ditindaklanjuti** (kode di DB tidak berubah: `new, reviewing, in_progress, done, rejected`, jadi data lama aman). Satpam dapat mengubah status (waktu + petugas tercatat di `feedback_history`) dan mengirim **tanggapan berkali-kali** (`feedback_responses`, tidak pernah menimpa). Mahasiswa melihat status, tanggapan, dan riwayat status di **Riwayat Kritik dan Saran** (`/feedback/mine`, `/feedback/mine/<id>`), hanya milik sendiri (404 untuk milik orang lain). Catatan internal Satpam tidak pernah ditampilkan ke mahasiswa.
- **Dashboard mahasiswa:** hanya 5 kritik dan saran terbaru (`LIMIT ?` + `WHERE user_id=?` di SQL) + tautan “Lihat Semua”. Riwayat lengkap tetap tersimpan dan dipaginasi (10/halaman).
- **Floating help button:** satu tombol bulat `position:fixed` kanan-bawah (memperhitungkan safe-area HP), tooltip “Panduan Penggunaan” di desktop, membuka satu-satunya modal panduan (ID/EN, dark/light, tutup via tombol/klik luar/Esc). Dirender hanya untuk non-Satpam di sisi server.
- **Notifikasi mahasiswa:** badge angka di menu *Riwayat Kritik dan Saran*, banner di dasbor, dan label **Baru** pada laporan yang punya perubahan status/tanggapan Satpam yang belum dibaca. Hilang otomatis saat pemilik membuka laporan.
- **Kritik dan saran tidak dikirim lewat email.** Semuanya masuk ke dashboard Satpam. EmailJS hanya dipakai untuk **Lupa Password**.
- **Daftar Satpam:** kolom jumlah tanggapan, label *Belum ditanggapi*, penanda laporan terbuka ≥3 hari, filter Tanggapan, balasan cepat, dan opsi ubah status sekaligus saat membalas.
- **Balasan mahasiswa:** setelah Satpam menanggapi, pemilik laporan bisa membalas di halaman detail (percakapan dua arah). Maksimal 3 balasan beruntun sebelum Satpam menjawab lagi, 5 balasan per 10 menit per akun, dan balasan tidak mengubah status. Satpam diberi tahu lewat badge menu, notice di dasbor/daftar, tag **Balasan baru**, dan filter *Ada balasan baru*.
- **Batas kirim masukan:** 5 per 10 menit per akun (login) dan 3 per 10 menit per IP (tamu).
- **Database:** skema **v7** (aditif): tabel `feedback_responses` (v5), kolom `feedback.rev` + `student_seen_rev` (v6, notifikasi mahasiswa), serta `feedback_responses.from_student` + `feedback.srev` + `staff_seen_srev` (v7, balasan mahasiswa dan notifikasi Satpam). Data lama tidak disentuh dan dianggap sudah dibaca.

## 0. Ringkasan revisi final
- **Bahasa ID/EN konsisten**: seluruh teks sumber di template kini bahasa Indonesia (Beranda, Tentang Kami, Cara Kerja, Fitur, Masuk, Daftar, Jelajahi Barang, Laporkan Barang, Kritik dan Saran, Dasbor, Keluar). Mode EN diterjemahkan dari kamus terpusat `services/translations.py`. Pilihan bahasa tersimpan di cookie.
- **Tema gelap/terang** terpusat di variabel CSS (`static/css/style.css`), tersimpan di `localStorage`, diverifikasi di browser untuk semua halaman.
- **Panduan lama dihapus** (menu sidebar, route `/guide`, halaman, tab Panduan Satpam, CSS/JS-nya). Penggantinya: **ikon “?”** yang membuka **modal panduan** (`templates/partials/help.html`), hanya dirender untuk mahasiswa/pengguna/tamu. **Satpam tidak mendapat ikon, menu, maupun isi panduan** (tidak ada di HTML-nya sama sekali).
- **Database bersih**: tidak ada seeder/data contoh. Dua akun demo dibuat tanpa data apa pun. Database lama yang pernah berisi data contoh dibersihkan satu kali otomatis (hanya baris `is_demo=1`).
- **Satpam berwenang penuh atas operasional**: verifikasi/tolak/pulihkan laporan temuan, tandai selesai/buka kembali/tolak laporan hilang, edit informasi laporan, hapus laporan tidak valid, proses pengembalian, riwayat aktivitas seluruh sistem, kelola kritik dan saran. Semua dicek di backend (`role_required("security")`).
- Skema database naik ke **v4** (status laporan `declined` + kolom tinjauan), migrasi otomatis dengan cadangan `.backup-vN`, data lama dipertahankan.

## 1. Menjalankan
**Windows / VS Code** (di dalam folder yang berisi `app.py`):
```
python -m venv venv
venv\Scripts\activate          (PowerShell: jika diblokir, pakai Command Prompt atau: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned)
pip install -r requirements.txt
copy .env.example .env
python app.py
```
Buka http://127.0.0.1:5000. Database dibuat/dimigrasi otomatis saat pertama jalan. Atau klik dua kali `run.bat`.

## 2. Akun demonstrasi (untuk dosen)
Tepat **dua** akun demo, dibuat otomatis (idempotent: restart tidak menggandakan). Di halaman **Masuk** tekan tombol, formulir terisi, lalu tekan **Masuk** sendiri.

| Tombol | Email | Password | Peran |
|---|---|---|---|
| Gunakan Demo Mahasiswa | `demo.user@itsb.test` | `DemoUser2026` | Mahasiswa |
| Gunakan Demo Satpam | `demo.satpam@itsb.test` | `DemoSatpam2026` | Satpam (bukan satpam utama) |

- **Kedua akun mulai benar-benar bersih**: tidak ada barang, laporan, riwayat, kritik/saran, atau statistik palsu. Semua angka 0 dan halaman menampilkan empty state.
- **Alur demonstrasi:** masuk sebagai Demo Mahasiswa → laporkan barang → masuk sebagai Demo Satpam → verifikasi/tolak/edit/hapus, proses pengembalian, kelola kritik dan saran.
- **Keamanan:** kredensial demo bersifat publik, sehingga Demo Satpam **hanya melihat dan mengelola data yang dibuat akun demo** (`is_demo=1`). Data pengguna sungguhan tidak terlihat dan tidak dapat diubah olehnya (404). Akun demo tidak bisa ganti password/profil dan tidak bisa di-reset.
- **Mengosongkan lagi setelah demonstrasi:** `python manage.py reset-demo --yes` (akun tetap ada, data asli aman).
- **Konfigurasi:** `DEMO_USER_EMAIL`, `DEMO_USER_PASSWORD`, `DEMO_SECURITY_EMAIL`, `DEMO_SECURITY_PASSWORD` di `.env`. `DEMO_ENABLED=0` mematikan akun demo.
- **Menghapus akun demo sekaligus aktivitasnya:** `python manage.py remove-demo --yes`, lalu set `DEMO_ENABLED=0`.

**Akun Satpam utama:** dibuat otomatis jika belum ada (`SECURITY_*` di `.env`, bawaan `satpam@itsb.test` / `Satpam12345`, **ganti sebelum dipakai sungguhan**). Satpam tambahan: `python manage.py create-security`. Satpam tidak bisa mendaftar lewat Register. Kolom lama `ADMIN_*` di `.env` tetap dibaca.

## 3. Fitur baru
**Panduan (ikon “?”)**: tombol bulat “?” di kanan atas halaman (dan di navbar halaman publik) membuka modal Panduan Penggunaan ITSB Find berisi 7 langkah (accordion) sesuai fitur yang benar-benar ada. Mengikuti bahasa dan tema aktif, responsif di layar kecil. Hanya dirender untuk non-Satpam; tidak ada halaman/route panduan.

**Wewenang Satpam:** menu Barang Temuan (Verifikasi, Tolak dengan alasan, Pulihkan, Edit, Hapus), Barang Hilang (Tandai selesai, Buka kembali, Tolak, Edit, Hapus), Pengembalian Barang, Riwayat Pengembalian, **Riwayat Aktivitas** (seluruh sistem), Kritik dan Saran. Barang yang sudah dikembalikan tidak dapat diedit/dihapus agar riwayat tetap utuh. Alasan penolakan terlihat oleh pelapor di “Laporan Saya”.

**Tema** (tombol matahari/bulan): variabel CSS terpusat di `static/css/style.css` (`:root` gelap, `:root[data-theme="light"]` terang yang dirancang sendiri). Pilihan disimpan di `localStorage`; tanpa pilihan mengikuti `prefers-color-scheme`. Diterapkan ke semua halaman, grafik, modal, tabel, form, dan sidebar. Kontras mode terang dihitung (teks utama 17:1, teks sekunder 7,3:1, aksen merah 5,3:1, lencana status ≥ 4,7:1).

**Bahasa** (tombol ID/EN): kamus terpusat di `services/translations.py` (satu baris `Indonesia => English`), mesin di `services/i18n.py`. Teks template tetap ditulis Indonesia dan diterjemahkan otomatis saat EN, jadi tidak ada template ganda. Mencakup navigasi, form, tombol, tabel, modal, panduan, flash, pesan validasi, JSON, tanggal, dan teks JavaScript. Isi yang ditulis pengguna (nama/deskripsi barang, isi masukan) tidak diterjemahkan. **Menambah teks baru:** tulis dalam Indonesia di template, tambahkan satu baris di kamus; ada pengujian yang gagal bila teks Indonesia tertinggal di halaman EN.

**Kritik dan Saran untuk Satpam** (`/satpam/feedback`): status Baru, Sedang Ditinjau, Sedang Dikerjakan, Selesai, Tidak Ditindaklanjuti (alasan wajib, min. 5 karakter). Halaman detail memuat pengirim, tanggal, kategori, isi, status, catatan internal, dan riwayat (status lama → baru, waktu, petugas, catatan). Statistik per status, filter status/kategori, pencarian nama/isi, urutan terbaru/terlama, 10 data per halaman. Pengirim yang login melihat status (dan alasan penolakan) di halaman Kritik dan Saran; **catatan internal tidak pernah terlihat pengguna**. Tidak bergantung pada EmailJS.

## 4. Profil & foto 5 anggota kelompok
Edit **satu file**: `config/team_members.py`. Setiap anggota: `name`, `nim`, `photo`, `github`, `linkedin`.
- **Foto:** simpan file di folder `static/images/team/` (JPG/JPEG/PNG/WEBP, disarankan persegi dan di bawah 500 KB), lalu isi `photo` dengan nama filenya. Jika `photo` kosong, sistem mencari file bernama `<NIM>.jpg` / `.jpeg` / `.png` / `.webp`. Jika file tidak ada, kartu menampilkan avatar inisial.
- Tombol GitHub dan LinkedIn hanya tampil jika link diisi (harus diawali `https://`).
- Berlaku di landing page dan About Us setelah login. Server perlu di-restart (atau refresh jika `FLASK_DEBUG=1`).

## 5. Logo ITSB FIND
Simpan file logo di `static/images/` dengan nama `logo.png` (atau `logo.svg`, `logo.webp`, `logo.jpg`), lalu refresh dengan Ctrl+F5. Logo otomatis tampil di navbar, sidebar, halaman login/register, footer, dan ikon tab browser. Jika file tidak ada, tampil logo bawaan.
Pengaturan tambahan di `config/branding.py`: `LOGO_FILE` (nama file lain), `SHOW_NAME` (tampilkan/sembunyikan teks "ITSB FIND" di samping logo), `LOGO_HEIGHT` (tinggi logo, px). Disarankan logo berlatar transparan dan terbaca di latar gelap.

> **Checklist produksi** (aplikasi mencatat peringatan `[KONFIGURASI]` saat start bila belum dipenuhi): `SECRET_KEY` acak panjang, `FLASK_DEBUG=0`, `SESSION_COOKIE_SECURE=1` (HTTPS), ganti `SECURITY_PASSWORD`, `DEMO_ENABLED=0`. Pembatas laju disimpan di memori per proses, jadi dengan banyak worker batasnya dihitung per worker.

## 6. Konfigurasi EmailJS (hanya Lupa Password)
Pengiriman dilakukan dari **backend Flask** lewat REST API EmailJS, sehingga token reset mentah dan Private Key tidak pernah ada di JavaScript browser, dan status sukses/gagal tercatat akurat.

1. Daftar di https://www.emailjs.com → **Email Services → Add New Service** (mis. Gmail) → hubungkan email pengirim. Catat **Service ID**.
2. **Account → General**: salin **Public Key**.
3. **Account → Security**: aktifkan **"Allow EmailJS API for non-browser applications"** (wajib, karena email dikirim dari server Flask). Jika Anda mengaktifkan opsi **Use Private Key**, salin Private Key dari **Account → API keys** dan isi `EMAILJS_PRIVATE_KEY` (opsional, hanya dipakai di backend).
4. **Email Templates → Create New Template**: isi dengan `emailjs_templates/reset_password.html`. **To Email** = `{{to_email}}`, **Subject** = `Reset password ITSB FIND`. Template memakai tepat dua variabel: `{{to_email}}` dan `{{link}}`. Catat **Template ID**.
5. Isi environment (file `.env` atau pengaturan deployment; **jangan di-commit**):
```
EMAILJS_SERVICE_ID=service_xxx
EMAILJS_TEMPLATE_ID=template_xxx
EMAILJS_PUBLIC_KEY=xxxx
# opsional: EMAILJS_PRIVATE_KEY=xxxx
APP_BASE_URL=https://USERNAME.pythonanywhere.com
```
   `APP_BASE_URL` **wajib** berisi URL deployment saat online. Jika kosong di server (bukan localhost), email reset sengaja tidak dikirim agar tautan tidak bisa dipalsukan lewat header Host.
6. Restart server. **Uji:** buka *Lupa Password?*, masukkan email akun asli (akun demo tidak bisa di-reset) → cek inbox → buka tautan → ganti password. Tautan berlaku **1 jam** dan hanya bisa dipakai **sekali**. EmailJS hanya dipakai untuk fitur ini; Kritik dan Saran disimpan di database dan dikelola dari dashboard Satpam.
7. **Email tidak terkirim?** Jalankan `python manage.py test-email EMAIL_ANDA`. Perintah ini menampilkan nilai EmailJS yang terbaca (rahasia disamarkan), apakah file `.env` ditemukan, mengirim email uji, dan menjelaskan kemungkinan penyebab jika gagal. Kesalahan paling umum: nilai diisi di `.env.example` (tidak dibaca; harus di file bernama `.env`), server belum di-restart setelah mengubah `.env`, atau opsi *non-browser* di EmailJS belum aktif.
8. Keamanan: token acak 256-bit, hanya hash SHA-256 yang disimpan, permintaan reset dibatasi (5 per jam per IP, 3 per jam per akun), respons selalu sama untuk email terdaftar maupun tidak, dan email dikirim di latar belakang sehingga waktu respons tidak membocorkan keberadaan akun. Password tidak pernah dikirim lewat email.
9. PythonAnywhere akun gratis membatasi koneksi keluar ke daftar situs tertentu. Jika email tidak terkirim, periksa log server (`Email reset password tidak terkirim`) dan pastikan `api.emailjs.com` dapat dijangkau dari akun Anda.


## 9. Variabel environment
| Variabel | Fungsi | Bawaan |
|---|---|---|
| `SECRET_KEY` | kunci sesi | (wajib diganti saat produksi) |
| `FLASK_DEBUG` | mode debug | 1 (isi 0 di produksi) |
| `APP_BASE_URL` | dasar tautan reset password (wajib saat online) | kosong (hanya localhost yang diizinkan) |
| `SESSION_COOKIE_SECURE` | cookie hanya lewat HTTPS | 0 (isi 1 di HTTPS) |
| `SECURITY_NAME/EMAIL/PHONE/PASSWORD` | akun Satpam utama awal | `satpam@itsb.test` / `Satpam12345` |
| `DEMO_ENABLED` | aktif/nonaktif akun demo | 1 |
| `DEMO_USER_EMAIL/PASSWORD`, `DEMO_SECURITY_EMAIL/PASSWORD` | kredensial demo | lihat bagian 2 |
| `EMAILJS_SERVICE_ID/TEMPLATE_ID/PUBLIC_KEY` (+ `EMAILJS_PRIVATE_KEY` opsional) | email Lupa Password lewat EmailJS REST API | kosong |

## 10. Deployment ke PythonAnywhere (Python 3.13)
1. Unggah proyek ke `/home/USERNAME/itsb_find` (git clone atau Upload/Files). **Saat memperbarui, jangan menimpa/menghapus** folder `database/`, `static/uploads/`, `instance/`, dan `.env`.
2. Konsol Bash: `mkvirtualenv --python=/usr/bin/python3.13 itsb` lalu `cd ~/itsb_find && pip install -r requirements.txt`.
3. `cp .env.example .env` lalu edit: `SECRET_KEY` (buat dengan `python -c "import secrets;print(secrets.token_hex(32))"`), `FLASK_DEBUG=0`, `APP_BASE_URL=https://USERNAME.pythonanywhere.com`, `SESSION_COOKIE_SECURE=1`, `SECURITY_*`, `DEMO_*`, `EMAILJS_*`.
4. Tab **Web** → Add a new web app → *Manual configuration* → Python 3.13. Isi: *Source code* dan *Working directory* = `/home/USERNAME/itsb_find`; *Virtualenv* = `/home/USERNAME/.virtualenvs/itsb`.
5. Klik file WSGI, ganti isinya dengan:
```python
import sys
path = '/home/USERNAME/itsb_find'
if path not in sys.path:
    sys.path.insert(0, path)
from wsgi import application
```
6. *Static files*: URL `/static/` → Directory `/home/USERNAME/itsb_find/static`. Aktifkan *Force HTTPS*.
7. Tekan **Reload**. Request pertama membuat/memigrasi database dan akun demo. Buka situs, uji login demo.
8. **Memperbarui versi:** cadangkan `database/itsb_find.db`, unggah file baru (tanpa menimpa data), Reload. Migrasi berjalan sendiri.
Catatan: nama file bersifat *case-sensitive* di Linux (mis. `logo.png`, foto tim sesuai `config/team_members.py`). Akun gratis PythonAnywhere membatasi koneksi keluar ke situs yang di-whitelist; jika `api.emailjs.com` tidak diizinkan, kritik saran tetap tersimpan tetapi status email "Gagal" (cek daftar whitelist di dokumentasi PythonAnywhere). Pembatas laju disimpan di memori per proses.

## 11. Pengujian
`python -m unittest tests.test_smoke -v` menjalankan 41 uji: akun demo (tepat dua, idempotent, tidak menimpa akun asli, Demo Satpam hanya data demo, akun demo terkunci), akses per peran (403), mode tamu, registrasi 4 jenis pengguna, privasi nomor telepon, alur pengembalian dengan foto privat, pengelolaan kritik saran (status, alasan wajib, riwayat, catatan internal tersembunyi, filter, pencarian, pagination, statistik), panduan, sistem tema, bahasa (cookie, redirect aman, nilai form tetap Indonesia, flash/JSON, tidak ada teks Indonesia tersisa di halaman EN), logo, tim, referensi file static (case-sensitive), migrasi v1→v3 dan v2→v3, serta database kosong.

**Belum teruji:** tampilan visual di browser (tema terang/gelap, responsivitas), eksekusi di Python 3.13 (diuji di 3.12), pengiriman email EmailJS asli, dan deployment nyata di PythonAnywhere.

## 12. Struktur
`app.py`, `wsgi.py`, `manage.py` · `config/` (settings, team_members, branding) · `database/` (db, init_db dan migrasi, demo) · `models/` · `routes/` (main, auth, user, feedback, satpam) · `services/` (security, matching, image_validation, email_service, password_reset, i18n, translations) · `templates/` · `static/` · `emailjs_templates/` · `tests/`.
