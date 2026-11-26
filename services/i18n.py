"""Terjemahan terpusat ID -> EN.
Teks sumber di template/route ditulis dalam bahasa Indonesia. Saat bahasa aktif = EN:
  - filter template (status, peran, tanggal) dan flash/JSON diterjemahkan lewat tr();
  - HTML hasil render diterjemahkan per-teks (teks persis + pola) oleh translate_html().
Kamus ada di services/translations.py. Teks yang tidak ada di kamus (mis. isi laporan pengguna) tidak diubah."""
import html as _html
import re

from flask import request

from services.translations import EXACT, JS_STRINGS, PATTERNS

LANGS = ("id", "en")


def get_lang():
    try:
        c = request.cookies.get("lang")
    except RuntimeError:
        c = None
    return c if c in LANGS else "id"


def _norm(t):
    return " ".join(t.split())


def tr(text, lang=None):
    """Terjemahkan satu string (Indonesia -> bahasa aktif). String tidak dikenal dikembalikan apa adanya."""
    if not isinstance(text, str) or not text.strip() or (lang or get_lang()) != "en":
        return text
    key = _norm(text)
    if key in EXACT:
        return EXACT[key]
    for rx, rep in PATTERNS:
        m = rx.fullmatch(key)
        if m:
            return rep(m, lambda x: tr(x, "en"))
    if " · " in key:                       # "Kategori · tanggal · Diperbarui ...": terjemahkan tiap bagian
        parts = [tr(p, "en") for p in key.split(" · ")]
        if parts != key.split(" · "):
            return " · ".join(parts)
    return text


def js_strings():
    return {k: EXACT.get(k, k) for k in JS_STRINGS} if get_lang() == "en" else {}


_SKIP = re.compile(r"(<(script|style|textarea)\b[^>]*>.*?</\2>)", re.S | re.I)
_TEXT = re.compile(r">([^<>]+)<")
_ATTR = re.compile(r'\b(placeholder|title|aria-label|alt|data-confirm)="([^"]*)"')
_META = re.compile(r'(<meta name="description" content=")([^"]*)(")')


def _text(m):
    raw = m.group(1)
    core = raw.strip()
    if not core:
        return m.group(0)
    out = tr(_html.unescape(core), "en")
    if out == _html.unescape(core):
        return m.group(0)
    lead, trail = raw[:len(raw) - len(raw.lstrip())], raw[len(raw.rstrip()):]
    return ">" + lead + _html.escape(out, quote=False) + trail + "<"


def _attr(m):
    out = tr(_html.unescape(m.group(2)), "en")
    return m.group(0) if out == _html.unescape(m.group(2)) else f'{m.group(1)}="{_html.escape(out, quote=True)}"'


def _meta(m):
    return m.group(1) + _html.escape(tr(_html.unescape(m.group(2)), "en"), quote=True) + m.group(3)


def translate_html(doc):
    parts = _SKIP.split(doc)       # [teks, blok, tag, teks, blok, tag, ...]
    out = []
    for i, seg in enumerate(parts):
        if i % 3 == 0:
            seg = _TEXT.sub(_text, seg)
            seg = _ATTR.sub(_attr, seg)
            seg = _META.sub(_meta, seg)
        elif i % 3 == 2:
            continue                # nama tag dari grup tangkapan
        out.append(seg)
    return "".join(out)
