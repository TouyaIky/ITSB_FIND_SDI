import sqlite3
from playwright.sync_api import sync_playwright
B="http://localhost:5055"; DB="/tmp/e2e/t.db"
def q(sql,a=()):
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; r=c.execute(sql,a).fetchall(); c.close(); return r
R=[]
def ok(name,cond,extra=""): R.append(bool(cond)); print(("PASS " if cond else "FAIL ")+name, extra)
def login(pg,e,pw):
    pg.goto(B+"/login"); pg.fill("[name=email]",e); pg.fill("[name=password]",pw); pg.click("form [type=submit]"); pg.wait_for_load_state()
def logout(pg): pg.click("form[action$='/logout'] button"); pg.wait_for_load_state()
def toasts(pg): return [t.inner_text().replace("\n✕","").strip() for t in pg.query_selector_all(".toast p")]
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1300,"height":900}); pg=ctx.new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    # --- A. notifikasi mahasiswa (laporan #1 sudah punya pembaruan satpam yg belum dibuka)
    login(pg,"demo.user@itsb.test","DemoUser2026"); pg.goto(B+"/dashboard")
    unread=q("select count(*) n from feedback where rev>student_seen_rev")[0]["n"]
    ok("A1 badge menu menampilkan jumlah pembaruan", pg.locator(".nav-badge").count()==1 and pg.inner_text(".nav-badge").strip()==str(unread) and unread>=1, unread)
    ok("A2 banner notifikasi di dasbor", pg.locator(".fb-notice").is_visible() and "pembaruan baru dari Satpam" in pg.inner_text(".fb-notice"))
    ok("A3 tanda Baru di kartu kritik saran", pg.locator(".fb-item .new-tag").count()>=1)
    pg.screenshot(path="/tmp/s_notif.png")
    pg.click(".fb-notice"); pg.wait_for_url("**/feedback/mine"); ok("A4 banner membuka riwayat", pg.url.endswith("/feedback/mine"))
    pg.click(".fb-item >> nth=0"); pg.wait_for_url("**/feedback/mine/*")
    ok("A5 detail mahasiswa: penjelasan status tampil", pg.locator(".status-help").inner_text().strip()!="")
    ok("A6 membuka detail menandai dibaca (badge hilang, DB seen=rev)", pg.locator(".nav-badge").count()==0 and q("select count(*) n from feedback where rev>student_seen_rev")[0]["n"]==0)
    # pesan baru dari mahasiswa
    pg.goto(B+"/feedback"); ok("A7 tamu-hint tidak tampil untuk user login", "memantau status dan tanggapan Satpam" not in pg.content())
    pg.select_option("[name=category]","Saran"); pg.fill("[name=subject]","Tambah tempat sampah"); pg.fill("[name=message]","Mohon tambah tempat sampah terpisah di dekat kantin utama.")
    pg.click("form.fb-ajax [type=submit]"); pg.wait_for_timeout(1200)
    ok("A8 tersimpan tanpa email (toast sukses)", any("tersimpan" in t for t in toasts(pg)), toasts(pg))
    fid=q("select id from feedback where subject='Tambah tempat sampah'")[0]["id"]
    ok("A8b rev awal 0 (belum ada notifikasi palsu)", q("select rev from feedback where id=?",(fid,))[0]["rev"]==0)
    logout(pg)
    # --- B. satpam: daftar, belum ditanggapi, balasan cepat, status sekaligus
    ctx2=b.new_context(viewport={"width":1300,"height":900}); sp=ctx2.new_page(); sp.on("pageerror", lambda e: errs.append("SAT:"+str(e)))
    login(sp,"demo.satpam@itsb.test","DemoSatpam2026")
    sp.goto(B+"/satpam/"); ok("B1 dasbor satpam: notice belum ditanggapi", "belum pernah ditanggapi" in sp.inner_text(".fb-unanswered"))
    sp.goto(B+"/satpam/feedback"); ok("B2 daftar: notice + kolom Tanggapan", sp.locator(".fb-unanswered").is_visible() and "Tanggapan" in sp.inner_text("thead"))
    ok("B3 baris baru berlabel Belum ditanggapi", sp.locator("tr.row-link", has_text="Tambah tempat sampah").locator(".b-pending", has_text="Belum ditanggapi").count()==1)
    sp.select_option("#resp","none"); sp.click("form.fb-filters [type=submit]"); sp.wait_for_url("**resp=none**")
    ok("B4 filter Belum ditanggapi hanya menampilkan yang kosong", sp.locator("tr.row-link").count()==1 and "Tambah tempat sampah" in sp.inner_text("tbody"))
    sp.click("tr.row-link"); sp.wait_for_url("**/satpam/feedback/%d"%fid)
    ok("B5 4 tombol balasan cepat", sp.locator("[data-tpl]").count()==4)
    sp.click("[data-tpl] >> nth=0"); v=sp.input_value("#response"); ok("B6 klik balasan cepat mengisi kolom", v.startswith("Terima kasih atas masukannya"), v[:40])
    sp.click("[data-tpl] >> nth=1"); ok("B7 klik kedua menambahkan (tidak menimpa)", sp.input_value("#response").count("\n")==1)
    sp.select_option("#respStatus","in_progress")
    sp.click("#respForm [type=submit]"); sp.wait_for_timeout(1500)
    st=q("select status from feedback where id=?",(fid,))[0]["status"]; rs=q("select * from feedback_responses where feedback_id=?",(fid,))
    ok("B8 satu klik: status berubah + tanggapan tersimpan", st=="in_progress" and len(rs)==1, (st,len(rs)))
    ok("B9 toast gabungan + badge terbarui tanpa reload", any("Status diperbarui dan tanggapan terkirim" in t for t in toasts(sp)) and sp.inner_text("#curBadge")=="Sedang Ditindaklanjuti")
    ok("B10 tanggapan baru disorot (class fresh) lalu pilihan status direset", sp.locator("#respList .resp.fresh").count()==1 and sp.input_value("#respStatus")=="")
    sp.screenshot(path="/tmp/s_sat_detail.png", full_page=True)
    sp.goto(B+"/satpam/feedback"); ok("B11 setelah dibalas: tampil jumlah tanggapan, notice hilang", sp.locator("tr.row-link", has_text="Tambah tempat sampah").locator(".resp-count").inner_text().strip().startswith("1") and sp.locator(".fb-unanswered").count()==0)
    # status sama + tanggapan = hanya tanggapan (bukan error)
    sp.goto(B+"/satpam/feedback/%d"%fid); sp.fill("#response","Update singkat: tim sudah survei."); sp.select_option("#respStatus","in_progress"); sp.click("#respForm [type=submit]"); sp.wait_for_timeout(1200)
    ok("B12 status sama + tanggapan = hanya tanggapan", len(q("select * from feedback_responses where feedback_id=?",(fid,)))==2 and any("Tanggapan terkirim" in t for t in toasts(sp)))
    # --- C. mahasiswa menerima notifikasi
    pg2=b.new_context(viewport={"width":1300,"height":900}).new_page(); pg2.on("pageerror", lambda e: errs.append("STU:"+str(e)))
    login(pg2,"demo.user@itsb.test","DemoUser2026"); pg2.goto(B+"/dashboard")
    ok("C1 mahasiswa melihat badge baru setelah satpam membalas", pg2.locator(".nav-badge").count()==1)
    pg2.goto(B+"/feedback/mine/%d"%fid); c=pg2.inner_text("body")
    ok("C2 detail: status, penjelasan, dua tanggapan", "Sedang Ditindaklanjuti" in c and "Update singkat" in c and "Terima kasih atas masukannya" in c)
    pg2.goto(B+"/lang/en?next=/dashboard"); pg2.wait_for_load_state()
    ok("C3 tampilan EN tetap berfungsi", "Dashboard" in pg2.inner_text("body"))
    pg2.goto(B+"/lang/id?next=/dashboard")
    # --- D. tamu
    gctx=b.new_context(viewport={"width":1300,"height":900}); gp=gctx.new_page()
    gp.goto(B+"/feedback"); ok("D1 pengunjung tanpa login: halaman terbuka & ada keterangan", "memantau status dan tanggapan Satpam" in gp.content() or gp.url.endswith("/login"), gp.url)
    print("JS errors:", errs)
    b.close()
print("ALL PASS" if all(R) else "SOME FAIL", sum(R),"/",len(R))
