import sqlite3
from playwright.sync_api import sync_playwright
B="http://localhost:5055"; DB="/tmp/e2e/t.db"
def q(sql,a=()):
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; r=c.execute(sql,a).fetchall(); c.close(); return r
R=[]
def ok(name,cond,extra=""): R.append(bool(cond)); print(("PASS " if cond else "FAIL ")+name, extra)
def login(pg,e,pw):
    pg.goto(B+"/login"); pg.fill("[name=email]",e); pg.fill("[name=password]",pw); pg.click("form [type=submit]"); pg.wait_for_load_state()
def toasts(pg): return [t.inner_text().replace("\n✕","").strip() for t in pg.query_selector_all(".toast p")]
with sync_playwright() as p:
    b=p.chromium.launch(); errs=[]
    st=b.new_context(viewport={"width":1300,"height":900}).new_page(); st.on("pageerror", lambda e: errs.append("STU:"+str(e)))
    login(st,"demo.user@itsb.test","DemoUser2026"); st.goto(B+"/feedback")
    st.select_option("[name=category]","Kritik"); st.fill("[name=subject]","Wifi lambat di kantin"); st.fill("[name=message]","Wifi di kantin sangat lambat saat jam makan siang, mohon diperbaiki.")
    st.click("form.fb-ajax [type=submit]"); st.wait_for_timeout(1200)
    fid=q("select id from feedback")[0]["id"]
    # 1. sebelum Satpam menanggapi: form balas tidak tersedia
    st.goto(B+"/feedback/mine/%d"%fid)
    ok("1 sebelum ditanggapi: form balas tersembunyi + petunjuk", not st.locator("#replyForm").is_visible() and "setelah Satpam memberikan tanggapan" in st.inner_text("#replyNote"))
    # 2. satpam menanggapi
    sp=b.new_context(viewport={"width":1300,"height":900}).new_page(); sp.on("pageerror", lambda e: errs.append("SAT:"+str(e)))
    login(sp,"demo.satpam@itsb.test","DemoSatpam2026"); sp.goto(B+"/satpam/feedback/%d"%fid)
    sp.click("[data-tpl] >> nth=1"); sp.click("#respForm [type=submit]"); sp.wait_for_timeout(1300)
    ok("2 satpam menanggapi", len(q("select * from feedback_responses where from_student=0"))==1)
    # 3. mahasiswa: form balas terbuka; kirim balasan
    st.goto(B+"/feedback/mine/%d"%fid)
    ok("3 setelah ditanggapi: form balas tampil", st.locator("#replyForm").is_visible())
    st.click("#replyForm [type=submit]"); st.wait_for_timeout(400)
    ok("3b validasi balasan kosong", st.locator("#replyForm .field-err").is_visible() and len(q("select * from feedback_responses where from_student=1"))==0, st.inner_text("#replyForm .field-err"))
    st.fill("#reply","Terima kasih Pak, kira-kira kapan perbaikannya selesai?")
    st.evaluate("const f=document.getElementById('replyForm'); f.requestSubmit(); f.requestSubmit(); f.requestSubmit();"); st.wait_for_timeout(1500)
    rs=q("select * from feedback_responses where from_student=1")
    ok("4 balasan tersimpan tepat 1 (anti kirim ganda), dikaitkan ke laporan & akun", len(rs)==1 and rs[0]["feedback_id"]==fid and rs[0]["created_by"] is not None)
    ok("4b tampil di percakapan sebagai 'Kamu', input kosong, toast sukses", st.locator("#respList .resp-mine").count()==1 and "Kamu" in st.inner_text("#respList .resp-mine") and st.input_value("#reply")=="" and any("Balasan terkirim" in t for t in toasts(st)), toasts(st))
    ok("4c balasan sendiri tidak membuat notifikasi untuk mahasiswa", st.locator(".nav-badge").count()==0)
    # 5. satpam melihat notifikasi
    sp.goto(B+"/satpam/feedback"); sp.wait_for_timeout(800)
    ok("5 satpam: badge menu + notice + tag Balasan baru", sp.locator(".nav-badge").count()==1 and "balasan baru dari pengirim" in sp.inner_text(".fb-unanswered") and sp.locator(".new-tag", has_text="Balasan baru").count()==1)
    sp.goto(B+"/satpam/"); ok("5b dasbor satpam menampilkan notice balasan", "balasan baru dari pengirim" in sp.inner_text(".fb-unanswered"))
    sp.goto(B+"/satpam/feedback?resp=reply"); ok("5c filter 'Ada balasan baru' menampilkan laporan ini", sp.locator("tr.row-link").count()==1)
    sp.click("tr.row-link td:nth-child(5)"); sp.wait_for_url("**/satpam/feedback/%d"%fid)
    ok("6 detail satpam menampilkan balasan dengan label Pengirim", sp.locator("#respList .resp-student").count()==1 and "Pengirim" in sp.inner_text("#respList .resp-student"))
    ok("6b notifikasi hilang setelah dibuka (DB + badge)", q("select srev=staff_seen_srev as s from feedback")[0]["s"]==1 and sp.locator(".nav-badge").count()==0)
    # 7. satpam menjawab lagi (live render ada percakapan campuran) -> mahasiswa dinotifikasi
    sp.fill("#response","Perbaikan dijadwalkan minggu depan."); sp.click("#respForm [type=submit]"); sp.wait_for_timeout(1300)
    ok("7 satpam balas: percakapan campuran 3 pesan, urut benar", sp.locator("#respList .resp").count()==3 and sp.locator("#respList .resp-student").count()==1)
    st.goto(B+"/dashboard"); ok("7b mahasiswa mendapat notifikasi atas jawaban satpam", st.locator(".nav-badge").count()==1)
    st.goto(B+"/feedback/mine/%d"%fid)
    ok("7c mahasiswa melihat 3 pesan dalam urutan waktu", st.locator("#respList .resp").count()==3 and "Perbaikan dijadwalkan" in st.inner_text("#respList .resp >> nth=2"))
    # 8. batas 3 balasan beruntun
    for i in range(3):
        st.fill("#reply",f"Balasan beruntun {i}"); st.click("#replyForm [type=submit]"); st.wait_for_timeout(1000)
    ok("8 setelah 3 balasan beruntun form ditutup + petunjuk tunggu Satpam", not st.locator("#replyForm").is_visible() and "Tunggu tanggapan Satpam" in st.inner_text("#replyNote"))
    ok("8b DB: 4 balasan mahasiswa", len(q("select * from feedback_responses where from_student=1"))==4)
    # 9. halaman satpam di HP: kartu ringkas
    mob=b.new_context(viewport={"width":390,"height":844}).new_page(); mob.on("pageerror", lambda e: errs.append("MOB:"+str(e)))
    login(mob,"demo.satpam@itsb.test","DemoSatpam2026"); mob.goto(B+"/satpam/feedback"); mob.wait_for_timeout(1000)
    ov=mob.evaluate("[document.documentElement.scrollWidth, innerWidth]"); ok("9 HP: tanpa overflow horizontal", ov[0]<=ov[1], ov)
    ok("9b HP: thead disembunyikan, tampil sebagai kartu", mob.evaluate("getComputedStyle(document.querySelector('.table-wrap thead')).position")=="absolute" and mob.evaluate("getComputedStyle(document.querySelector('tr.row-link')).display")=="flex")
    firstcell=mob.evaluate("document.querySelector('tr.row-link').getBoundingClientRect().top"); subj=mob.evaluate("document.querySelector('td.fb-c-subject').getBoundingClientRect().top"); send=mob.evaluate("document.querySelector('td.fb-c-sender').getBoundingClientRect().top")
    ok("9c HP: subjek paling atas, pengirim di bawahnya", subj<send, (round(subj),round(send)))
    mob.screenshot(path="/tmp/m_list2.png", full_page=True)
    mob.click("tr.row-link"); mob.wait_for_url("**/satpam/feedback/%d"%fid); ok("9d HP: ketuk kartu membuka detail", True)
    mob.screenshot(path="/tmp/m_detail2.png", full_page=True)
    st2=b.new_context(viewport={"width":390,"height":844}).new_page(); login(st2,"demo.user@itsb.test","DemoUser2026"); st2.goto(B+"/feedback/mine/%d"%fid); st2.wait_for_timeout(800)
    ov=st2.evaluate("[document.documentElement.scrollWidth, innerWidth]"); ok("9e HP mahasiswa: detail percakapan tanpa overflow", ov[0]<=ov[1], ov); st2.screenshot(path="/tmp/m_stu_detail.png", full_page=True)
    print("JS errors:", errs)
    b.close()
print("ALL PASS" if all(R) else "SOME FAIL", sum(R),"/",len(R))
