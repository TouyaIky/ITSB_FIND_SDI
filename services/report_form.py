"""Pembacaan & validasi formulir laporan (barang hilang/temuan). Dipakai oleh pengguna (membuat) dan Satpam (mengedit)."""
from datetime import date, datetime

from flask import request

from config import settings as S
from services.security import valid_phone

FIELDS = ("item_name", "category", "description", "location", "date", "time", "phone")


def read_report_form():
    """Return (data, error). Pesan error ditulis dalam bahasa Indonesia dan diterjemahkan otomatis sesuai bahasa aktif."""
    d = {k: request.form.get(k, "").strip() for k in FIELDS}
    err = None
    phone, phone_err = valid_phone(d["phone"])
    if not all(d.values()):
        err = "Seluruh kolom wajib diisi, termasuk nomor telepon."
    elif d["category"] not in S.CATEGORIES:
        err = "Kategori tidak valid."
    elif len(d["item_name"]) > 100 or len(d["location"]) > 100 or not 10 <= len(d["description"]) <= 1000:
        err = "Nama/lokasi maksimal 100 karakter dan deskripsi 10–1000 karakter."
    elif phone_err:
        err = phone_err
    else:
        d["phone"] = phone
        try:
            dt = date.fromisoformat(d["date"])
            datetime.strptime(d["time"], "%H:%M")
            if dt > date.today():
                err = "Tanggal tidak boleh di masa depan."
        except ValueError:
            err = "Format tanggal atau waktu tidak valid."
    return d, err
