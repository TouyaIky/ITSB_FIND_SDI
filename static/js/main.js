(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (window.lucide) lucide.createIcons();
  requestAnimationFrame(() => document.body.classList.add('ready'));
  window.addEventListener('pageshow', () => document.body.classList.remove('leaving'));

  /* Toasts */
  window.toast = function (msg, type = 'info', ms = 5200) {
    const box = $('#toasts'); if (!box) return;
    const el = document.createElement('div');
    el.className = 'toast ' + type; el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    const p = document.createElement('p'); p.textContent = msg;
    const b = document.createElement('button'); b.type = 'button'; b.setAttribute('aria-label', __('Tutup')); b.textContent = '✕';
    el.append(p, b); box.appendChild(el);
    const close = () => { el.classList.add('out'); setTimeout(() => el.remove(), 300); };
    b.onclick = close; setTimeout(close, ms);
  };
  try { JSON.parse($('#flash-data')?.textContent || '[]').forEach(([c, m]) => toast(m, c === 'message' ? 'info' : c)); } catch (e) {}

  /* Modals */
  window.openModal = id => { const m = document.getElementById(id); if (m) { m.classList.add('open'); document.body.style.overflow = 'hidden'; } };
  window.closeModal = m => { m.classList.remove('open'); document.body.style.overflow = ''; };
  document.addEventListener('click', e => {
    const o = e.target.closest('[data-modal-open]'); if (o) { e.preventDefault(); openModal(o.dataset.modalOpen); }
    const x = e.target.closest('[data-modal-close]'); if (x) closeModal(x.closest('.modal'));
    if (e.target.classList?.contains('modal')) closeModal(e.target);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $$('.modal.open').forEach(closeModal); });

  /* Konfirmasi aksi */
  document.addEventListener('submit', e => {
    const c = e.target.dataset.confirm; if (c && !confirm(c)) e.preventDefault();
  });

  /* Password show/hide */
  document.addEventListener('click', e => {
    const b = e.target.closest('.eye'); if (!b) return;
    const inp = b.parentElement.querySelector('input'); const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password'; b.setAttribute('aria-label', show ? __('Sembunyikan password') : __('Tampilkan password'));
    b.innerHTML = `<i data-lucide="${show ? 'eye-off' : 'eye'}" class="i"></i>`; lucide.createIcons();
  });

  /* Tema terang/gelap: tersimpan di localStorage; tanpa pilihan mengikuti preferensi perangkat */
  const root = document.documentElement;
  const applyTheme = (t, save) => {
    root.setAttribute('data-theme', t);
    try { if (save) localStorage.setItem('itsb-theme', t); } catch (e) {}
    const m = document.querySelector('meta[name=theme-color]'); if (m) m.setAttribute('content', t === 'light' ? '#f4f5f9' : '#07080c');
    window.dispatchEvent(new CustomEvent('themechange', { detail: t }));
  };
  document.addEventListener('click', e => { if (e.target.closest('[data-theme-toggle]')) applyTheme(root.getAttribute('data-theme') === 'light' ? 'dark' : 'light', true); });
  try {
    matchMedia('(prefers-color-scheme: light)').addEventListener('change', ev => {
      let saved = null; try { saved = localStorage.getItem('itsb-theme'); } catch (e) {}
      if (saved !== 'light' && saved !== 'dark') applyTheme(ev.matches ? 'light' : 'dark', false);
    });
  } catch (e) {}

  /* Akun demo: hanya mengisi formulir; pengguna tetap menekan Login */
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-demo]'); if (!b) return;
    const form = document.querySelector('form [name=email]')?.form; if (!form) return;
    form.email.value = b.dataset.email; form.password.value = b.dataset.password;
    document.querySelectorAll('[data-demo-note]').forEach(n => n.hidden = n.dataset.demoNote !== b.dataset.demo);
    form.querySelector('[type=submit]')?.focus();
  });

  /* Mencegah submit ganda + loading state */
  $$('form[data-once]').forEach(f => f.addEventListener('submit', () => {
    const b = f.querySelector('[type=submit]'); if (!b || b.disabled) return;
    setTimeout(() => { b.disabled = true; b.dataset.t = b.innerHTML; b.innerHTML = '<span class="spinner"></span> ' + __('Memproses…'); }, 0);
  }));

  /* Navbar */
  const nav = $('.nav');
  if (nav) {
    const on = () => nav.classList.toggle('scrolled', scrollY > 20); on(); addEventListener('scroll', on, { passive: true });
    const burger = $('.burger'), menu = $('.nav-menu');
    burger?.addEventListener('click', () => { const o = menu.classList.toggle('open'); burger.setAttribute('aria-expanded', o); });
    menu?.addEventListener('click', e => { if (e.target.closest('a')) menu.classList.remove('open'); });
    const links = $$('.nav-links a[data-section]');
    if (links.length && 'IntersectionObserver' in window) {
      const map = {}; links.forEach(a => a.dataset.section.split(' ').forEach(s => map[s] = a));
      const io = new IntersectionObserver(es => es.forEach(en => {
        if (en.isIntersecting && map[en.target.id]) { links.forEach(l => l.classList.remove('active')); map[en.target.id].classList.add('active'); }
      }), { rootMargin: '-45% 0px -50% 0px' });
      Object.keys(map).forEach(id => { const s = document.getElementById(id); if (s) io.observe(s); });
    }
  }

  /* Sidebar mobile */
  const side = $('.side'), scrim = $('.scrim');
  $('#sideToggle')?.addEventListener('click', () => { side.classList.toggle('open'); scrim.classList.toggle('open'); });
  scrim?.addEventListener('click', () => { side.classList.remove('open'); scrim.classList.remove('open'); });

  /* Scroll reveal */
  const rv = $$('.reveal');
  if ('IntersectionObserver' in window && !reduce) {
    const io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); } }), { threshold: .12 });
    rv.forEach((el, i) => { el.style.transitionDelay = (el.dataset.d || 0) + 'ms'; io.observe(el); });
  } else rv.forEach(el => el.classList.add('in'));

  /* Counter */
  const counters = $$('[data-count]');
  const run = el => {
    const target = +el.dataset.count, t0 = performance.now(), dur = 1300;
    if (reduce || target === 0) { el.textContent = target.toLocaleString('id-ID'); return; }
    const tick = t => { const p = Math.min(1, (t - t0) / dur); el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))).toLocaleString('id-ID'); if (p < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  };
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) { run(en.target); io.unobserve(en.target); } }), { threshold: .4 });
    counters.forEach(c => io.observe(c));
  } else counters.forEach(run);

  /* Spotlight pada kartu fitur */
  $$('.feature').forEach(c => c.addEventListener('pointermove', e => {
    const r = c.getBoundingClientRect(); c.style.setProperty('--mx', (e.clientX - r.left) + 'px'); c.style.setProperty('--my', (e.clientY - r.top) + 'px');
  }));

  /* Partikel ringan */
  const cv = $('#particles');
  if (cv && !reduce) {
    const ctx = cv.getContext('2d'); let w, h, pts = [], raf;
    const size = () => { w = cv.width = cv.offsetWidth; h = cv.height = cv.offsetHeight; pts = Array.from({ length: Math.min(46, Math.floor(w / 28)) }, () => ({ x: Math.random() * w, y: Math.random() * h, vx: (Math.random() - .5) * .25, vy: (Math.random() - .5) * .25, r: Math.random() * 1.4 + .4 })); };
    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      pts.forEach((p, i) => {
        p.x += p.vx; p.y += p.vy; if (p.x < 0 || p.x > w) p.vx *= -1; if (p.y < 0 || p.y > h) p.vy *= -1;
        ctx.fillStyle = 'rgba(255,90,100,.7)'; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
        for (let j = i + 1; j < pts.length; j++) { const q = pts[j], d = Math.hypot(p.x - q.x, p.y - q.y); if (d < 120) { ctx.strokeStyle = `rgba(255,77,90,${.14 * (1 - d / 120)})`; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke(); } }
      });
      raf = requestAnimationFrame(draw);
    };
    size(); draw(); addEventListener('resize', size);
    document.addEventListener('visibilitychange', () => { document.hidden ? cancelAnimationFrame(raf) : draw(); });
  }

  /* Transisi halaman */
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href]'); if (e.defaultPrevented || !a || e.metaKey || e.ctrlKey || e.shiftKey || a.target === '_blank') return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || (u.pathname === location.pathname && u.hash) || a.hasAttribute('download')) return;
    if (reduce) return;
    e.preventDefault(); document.body.classList.add('leaving'); setTimeout(() => location.href = a.href, 220);
  });
})();


/* Tabel responsif: salin teks <th> ke data-label tiap <td> (dipakai CSS untuk tampilan kartu di HP) */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.table-wrap table').forEach(t => {
    const heads = [...t.querySelectorAll('thead th')].map(th => th.textContent.trim());
    t.querySelectorAll('tbody tr').forEach(tr => [...tr.children].forEach((td, i) => { if (td.tagName === 'TD') td.setAttribute('data-label', heads[i] || ''); }));
  });
});
