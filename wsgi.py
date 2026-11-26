"""Titik masuk WSGI (PythonAnywhere / server produksi). Di PythonAnywhere, isi file WSGI konfigurasi web app dengan:

    import sys
    path = '/home/USERNAME/itsb_find'          # ganti USERNAME dan nama folder proyek
    if path not in sys.path:
        sys.path.insert(0, path)
    from wsgi import application
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app as application  # noqa: E402
