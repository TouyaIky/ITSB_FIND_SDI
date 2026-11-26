/* Kritik & Saran (Satpam): ubah status & kirim tanggapan via fetch (JSON), tanpa reload halaman.
   Tanpa JavaScript, form tetap bekerja lewat POST biasa + redirect (fallback di route). */
(function () {
  /* Daftar: seluruh baris membuka detail */
  document.querySelectorAll('tr.row-link[data-href]').forEach(tr => tr.addEventListener('click', e => {
    if (e.target.closest('a,button,input,select,textarea')) return; location.href = tr.dataset.href;
  }));

  const sel = document.getElementById('status');
  const statusForm = document.getElementById('statusForm'), respForm = document.getElementById('respForm');
  if (!statusForm || !respForm || !sel) return;
  const save = document.getElementById('statusSave'), reasonField = document.getElementById('reasonField'), reason = document.getElementById('reason');
  const $ = id => document.getElementById(id);
  const icons = () => { if (window.lucide) lucide.createIcons(); };

  const errBox = (form, text) => { const e = form.querySelector('.field-err'); if (!e) return; e.textContent = text || ''; e.hidden = !text; };
  const busy = (form, on, text) => {
    const b = form.querySelector('[type=submit]'), l = b.querySelector('.lbl');
    if (on) { b.dataset.html = b.innerHTML; b.disabled = true; b.innerHTML = '<span class="spinner"></span> <span class="lbl">' + text + '</span>'; }
    else { b.disabled = false; if (b.dataset.html) b.innerHTML = b.dataset.html; icons(); }
  };
  async function post(form, payload) {
    const res = await fetch(form.action, { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-Requested-With': 'fetch', 'X-CSRF-Token': form.querySelector('[name=_csrf]').value },
      body: JSON.stringify(payload) });
    const data = await res.json().catch(() => ({ ok: false, message: __('Respons server tidak valid.') }));
    if (res.status === 403 || res.status === 401) data.message = data.message || __('Sesi berakhir. Muat ulang halaman lalu masuk kembali.');
    return data;
  }

  /* Render ulang dari snapshot server: tampilan = isi database */
  function render(d, opt) {
    const badge = $('curBadge'); badge.className = 'badge ' + d.cls; badge.textContent = d.label;
    sel.dataset.current = d.status; sel.value = d.status; syncStatus();
    if (d.handler) { $('handledRow').hidden = false; $('handledVal').textContent = d.handler + ' · ' + d.updated_at; }
    const hl = $('histList'); hl.textContent = '';
    d.history.forEach(h => {
      const li = document.createElement('li'), b = document.createElement('b');
      const badge = (cls, t) => { const s = document.createElement('span'); s.className = 'badge ' + cls; s.textContent = t; return s; };
      if (h.old_label) { b.append(badge(h.old_cls, h.old_label), ' → '); }
      b.append(badge(h.new_cls, h.new_label)); li.append(b);
      const sm = document.createElement('small'); sm.textContent = h.at + ' · ' + h.actor; li.append(sm);
      if (h.note) { const n = document.createElement('div'); n.className = 'tl-note'; n.textContent = h.note; li.append(n); }
      hl.append(li);
    });
    const rl = $('respList'); rl.textContent = '';
    d.responses.forEach((r, i) => {
      const li = document.createElement('li'); li.className = 'resp' + (r.from_student ? ' resp-student' : '');
      const head = document.createElement('div'); head.className = 'resp-head';
      const o = document.createElement('b'); o.textContent = r.officer;
      if (r.from_student) { const tag = document.createElement('span'); tag.className = 'badge b-info'; tag.textContent = __('Pengirim'); o.append(' ', tag); }
      const t = document.createElement('small'); t.textContent = r.at; head.append(o, t);
      const body = document.createElement('div'); body.className = 'resp-body'; body.textContent = r.message; li.append(head, body);
      if (i === d.responses.length - 1) li.dataset.new = '1';
      rl.append(li);
    });
    rl.hidden = !d.responses.length; $('respEmpty').hidden = d.responses.length > 0; $('respCount').textContent = d.responses.length;
    const last = rl.querySelector('[data-new]'); if (last) last.removeAttribute('data-new');
    if (opt && opt.focusResponse && last) {            // arahkan pandangan ke tanggapan yang baru dikirim
      last.classList.add('fresh');
      last.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      setTimeout(() => last.classList.remove('fresh'), 2800);
    }
  }

  /* Dropdown status: tombol Simpan Perubahan hanya muncul bila status berbeda */
  function syncStatus() {
    const changed = sel.value !== sel.dataset.current;
    save.hidden = !changed; reasonField.hidden = !changed; errBox(statusForm, '');
    if (!changed) reason.value = '';
  }
  sel.addEventListener('change', syncStatus); syncStatus();

  let sBusy = false;
  statusForm.addEventListener('submit', async e => {
    e.preventDefault(); if (sBusy) return;
    if (sel.value === sel.dataset.current) { const m = __('Status tidak berubah.'); errBox(statusForm, m); toast(m, 'error'); return; }
    if (sel.value === 'rejected' && reason.value.trim().length < 5) {
      const m = __('Alasan wajib diisi (minimal 5 karakter) untuk status Tidak Dapat Ditindaklanjuti.'); errBox(statusForm, m); toast(m, 'error'); reason.focus(); return;
    }
    sBusy = true; busy(statusForm, true, __('Menyimpan…'));
    try {
      const d = await post(statusForm, { status: sel.value, reason: reason.value });
      if (d.ok) { render(d); toast(d.message, 'success'); } else { errBox(statusForm, d.message); toast(d.message, 'error'); }
    } catch (err) { const m = __('Gagal terhubung ke server. Periksa koneksi internet Anda.'); errBox(statusForm, m); toast(m, 'error'); }
    sBusy = false; busy(statusForm, false); syncStatus();
  });

  let rBusy = false;
  const ta = $('response'), respStatus = $('respStatus');
  respForm.querySelectorAll('[data-tpl]').forEach(b => b.addEventListener('click', () => {   // balasan cepat: isi/tambahkan ke kolom
    ta.value = ta.value.trim() ? ta.value.trim() + '\n' + b.dataset.tpl : b.dataset.tpl;
    ta.dispatchEvent(new Event('input')); ta.focus();
  }));
  ta.addEventListener('input', () => errBox(respForm, ''));
  respForm.addEventListener('submit', async e => {
    e.preventDefault(); if (rBusy) return;
    if (ta.value.trim().length < 3) { const m = __('Tanggapan wajib diisi (minimal 3 karakter).'); errBox(respForm, m); toast(m, 'error'); ta.focus(); return; }
    rBusy = true; busy(respForm, true, __('Mengirim…'));
    try {
      const d = await post(respForm, { response: ta.value, status: respStatus.value });
      if (d.ok) { render(d, { focusResponse: true }); respStatus.value = ''; ta.value = ''; ta.dispatchEvent(new Event('input')); toast(d.message, 'success'); }
      else { errBox(respForm, d.message); toast(d.message, 'error'); }
    } catch (err) { const m = __('Gagal terhubung ke server. Periksa koneksi internet Anda.'); errBox(respForm, m); toast(m, 'error'); }
    rBusy = false; busy(respForm, false);
  });
})();
