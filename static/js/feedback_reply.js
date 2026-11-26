/* Balasan mahasiswa pada detail kritik & saran: kirim via fetch (JSON), tampilan diperbarui dari data server tanpa reload.
   Tanpa JavaScript, form tetap bekerja lewat POST biasa + redirect. */
(function () {
  const form = document.getElementById('replyForm'); if (!form) return;
  const $ = id => document.getElementById(id), ta = $('reply'), err = form.querySelector('.field-err');
  const icons = () => { if (window.lucide) lucide.createIcons(); };
  const showErr = t => { err.textContent = t || ''; err.hidden = !t; };

  function render(d) {
    const rl = $('respList'); rl.textContent = '';
    d.responses.forEach((r, i) => {
      const li = document.createElement('li'); li.className = 'resp' + (r.mine ? ' resp-mine' : '');
      const head = document.createElement('div'); head.className = 'resp-head';
      const b = document.createElement('b'); b.textContent = r.author; const t = document.createElement('small'); t.textContent = r.at; head.append(b, t);
      const body = document.createElement('div'); body.className = 'resp-body'; body.textContent = r.message; li.append(head, body);
      if (i === d.responses.length - 1) li.dataset.new = '1';
      rl.append(li);
    });
    rl.hidden = !d.responses.length; $('respEmpty').hidden = d.responses.length > 0; $('respCount').textContent = d.count;
    form.hidden = !d.can_reply; $('replyNote').textContent = d.reply_hint || ''; $('replyNote').hidden = !d.reply_hint;
    const last = rl.querySelector('[data-new]');
    if (last) {                                                  // arahkan pandangan ke balasan yang baru terkirim
      last.removeAttribute('data-new'); last.classList.add('fresh');
      last.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      setTimeout(() => last.classList.remove('fresh'), 2800);
    }
  }

  let busy = false;
  ta.addEventListener('input', () => showErr(''));
  form.addEventListener('submit', async e => {
    e.preventDefault(); if (busy) return;
    if (ta.value.trim().length < 3) { const m = __('Balasan wajib diisi (minimal 3 karakter).'); showErr(m); toast(m, 'error'); ta.focus(); return; }
    busy = true;
    const btn = form.querySelector('[type=submit]'), html = btn.innerHTML;
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> <span class="lbl">' + __('Mengirim…') + '</span>';
    try {
      const res = await fetch(form.action, { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-Requested-With': 'fetch', 'X-CSRF-Token': form.querySelector('[name=_csrf]').value },
        body: JSON.stringify({ response: ta.value }) });
      const d = await res.json().catch(() => ({ ok: false, message: __('Respons server tidak valid.') }));
      if (d.ok) { render(d); ta.value = ''; ta.dispatchEvent(new Event('input')); toast(d.message, 'success'); }
      else { showErr(d.message); toast(d.message, 'error'); }
    } catch (x) { const m = __('Gagal terhubung ke server. Periksa koneksi internet Anda.'); showErr(m); toast(m, 'error'); }
    busy = false; btn.disabled = false; btn.innerHTML = html; icons();
  });
})();
