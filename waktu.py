"""Satu-satunya sumber waktu aplikasi: WIB (UTC+7).

Server hosting (Railway dll.) berjalan di UTC. Modul ini dipakai oleh semua file
Python (config, app, auto_alpa, pembimbing_pkl) agar waktu selalu WIB.
Indonesia (WIB) tidak mengenal DST, jadi offset tetap +7 sudah cukup dan
tidak butuh paket tzdata.
"""
import os
import time
from datetime import date, datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))
NAMA_ZONA = 'Asia/Jakarta'

# Paksa zona waktu proses (format POSIX, tanpa tzdata) agar datetime.now()
# yang tidak sengaja terpakai pun tetap WIB. Tidak ada di Windows -> dilewati.
os.environ['TZ'] = 'WIB-7'
if hasattr(time, 'tzset'):
    time.tzset()


def sekarang_wib():
    """Waktu sekarang di WIB, timezone-aware."""
    return datetime.now(WIB)


def now_wib():
    """Waktu sekarang di WIB, naive (cocok untuk dibandingkan/ditulis ke MySQL)."""
    return sekarang_wib().replace(tzinfo=None)


def today_wib() -> date:
    return now_wib().date()
