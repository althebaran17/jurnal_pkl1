"""Auto-Alpa massal (batas jam 15:00 WIB).

Kenapa modul ini ada
--------------------
Versi lama (`cek_dan_set_alpa_otomatis`) hanya berjalan ketika SISWA membuka
halaman dashboard/absensi/pengajuan. Siswa yang tidak login sama sekali tidak
pernah dicatat Alpa. Di sini pengecekan dilakukan untuk SEMUA siswa aktif,
tanpa menunggu siswa login, lewat tiga jalur yang aman dijalankan bersamaan:

1. Thread latar belakang di tiap proses web (cek tiap 60 detik).
2. Pemanggilan dari helper lama (per siswa) saat siswa membuka halamannya.
3. Perintah CLI untuk cron:  flask --app app auto-alpa

Aturan (sama dengan aturan lama, hanya dibuat massal)
-----------------------------------------------------
* Hari Minggu tidak dihitung.
* Hanya hari dalam periode PKL siswa (tgl_mulai_pkl .. tgl_selesai_pkl).
* Akun siswa yang dinonaktifkan dilewati.
* Hari ini baru dihitung setelah pukul 15:00 WIB; hari-hari sebelumnya
  yang terlewat (server mati / thread belum jalan) ikut disusulkan.
* Tidak dicatat Alpa bila sudah ada baris absensi, atau ada pengajuan
  Izin/Sakit berstatus Pending/Disetujui. Pengajuan Terlambat yang
  Pending/Disetujui hanya membebaskan HARI INI (siswa masih boleh selfie
  setelah di-ACC); pada hari yang sudah lewat tetap dihitung Alpa.

Penyisipan memakai INSERT ... WHERE NOT EXISTS sehingga aman bila beberapa
proses/worker berjalan bersamaan.
"""
import threading
import time as _time
from datetime import date, datetime, time, timedelta, timezone

from config import get_db_connection

# WIB = UTC+7 dan tidak mengenal DST, jadi offset tetap sudah cukup
# (tidak bergantung pada tzdata / zona waktu server).
WIB = timezone(timedelta(hours=7))
JAM_BATAS_ALPA = time(15, 0)
INTERVAL_DETIK = 60

# Ubah ke False bila hanya ingin mengisi Alpa untuk HARI INI (tanpa menyusul
# hari-hari lampau yang belum tercatat).
SUSULKAN_HARI_LAMPAU = True

KETERANGAN_ALPA = 'Otomatis Alpa oleh Sistem (Lewat Jam 15:00 WIB)'

_sapu_lock = threading.Lock()   # satu penyapuan pada satu waktu per proses
_start_lock = threading.Lock()
_thread = None


def sekarang_wib():
    return datetime.now(WIB)


def _ke_date(nilai):
    if nilai is None or nilai == '':
        return None
    if isinstance(nilai, datetime):
        return nilai.date()
    if isinstance(nilai, date):
        return nilai
    return datetime.strptime(str(nilai)[:10], '%Y-%m-%d').date()


def hitung_alpa_tertunda(siswa_rows, absensi_ada, pengajuan_bebas, pengajuan_terlambat,
                         sekarang, susulkan=SUSULKAN_HARI_LAMPAU):
    """Murni (tanpa DB): kembalikan daftar (siswa_id, date) yang harus di-Alpa-kan."""
    hari_ini = sekarang.date()
    sudah_lewat_batas = sekarang.time() >= JAM_BATAS_ALPA
    hari_terakhir = hari_ini if sudah_lewat_batas else hari_ini - timedelta(days=1)

    hasil = []
    for s in siswa_rows:
        sid = s['id']
        mulai = _ke_date(s.get('tgl_mulai_pkl'))
        selesai = _ke_date(s.get('tgl_selesai_pkl'))

        # Tanpa tanggal mulai tidak ada patokan "sejak kapan" -> hanya hari ini.
        awal = hari_ini
        if mulai:
            awal = mulai if susulkan else max(mulai, hari_ini)
        akhir = min(selesai, hari_terakhir) if selesai else hari_terakhir
        if mulai and mulai > hari_ini:
            continue

        d = awal
        while d <= akhir:
            if d.weekday() != 6:  # 6 = Minggu
                kunci = (sid, d)
                bebas = (
                    kunci in absensi_ada
                    or kunci in pengajuan_bebas
                    or (d == hari_ini and kunci in pengajuan_terlambat)
                )
                if not bebas:
                    hasil.append(kunci)
            d += timedelta(days=1)
    return hasil


def jalankan_auto_alpa(siswa_id=None, sekarang=None, susulkan=SUSULKAN_HARI_LAMPAU):
    """Catat Alpa untuk semua (atau satu) siswa. Mengembalikan jumlah baris baru."""
    sekarang = sekarang or sekarang_wib()
    conn = get_db_connection()
    if not conn:
        return 0
    cursor = conn.cursor(dictionary=True)
    try:
        sql = """
            SELECT s.id, s.tgl_mulai_pkl, s.tgl_selesai_pkl
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            WHERE COALESCE(u.is_active, 1) <> 0
        """
        params = []
        if siswa_id is not None:
            sql += " AND s.id = %s"
            params.append(siswa_id)
        cursor.execute(sql, tuple(params))
        siswa_rows = cursor.fetchall()
        if not siswa_rows:
            return 0

        hari_ini = sekarang.date()
        paling_awal = hari_ini
        if susulkan:
            for s in siswa_rows:
                m = _ke_date(s.get('tgl_mulai_pkl'))
                if m and m < paling_awal:
                    paling_awal = m
        rentang = (paling_awal.isoformat(), hari_ini.isoformat())

        filter_siswa = ""
        extra = []
        if siswa_id is not None:
            filter_siswa = " AND siswa_id = %s"
            extra = [siswa_id]

        cursor.execute(
            "SELECT siswa_id, tanggal FROM absensi WHERE tanggal BETWEEN %s AND %s" + filter_siswa,
            (*rentang, *extra))
        absensi_ada = {(r['siswa_id'], _ke_date(r['tanggal'])) for r in cursor.fetchall()}

        cursor.execute(
            "SELECT siswa_id, tanggal, jenis FROM pengajuan_absensi "
            "WHERE tanggal BETWEEN %s AND %s AND status_pengajuan IN ('Pending', 'Disetujui')"
            + filter_siswa,
            (*rentang, *extra))
        pengajuan_bebas, pengajuan_terlambat = set(), set()
        for r in cursor.fetchall():
            kunci = (r['siswa_id'], _ke_date(r['tanggal']))
            if r['jenis'] == 'Terlambat':
                pengajuan_terlambat.add(kunci)
            else:
                pengajuan_bebas.add(kunci)

        tertunda = hitung_alpa_tertunda(
            siswa_rows, absensi_ada, pengajuan_bebas, pengajuan_terlambat, sekarang, susulkan)

        baru = 0
        for sid, tgl in tertunda:
            cursor.execute("""
                INSERT INTO absensi (siswa_id, tanggal, status, keterangan, is_manual, created_at)
                SELECT %s, %s, 'Alpa', %s, 0, NOW() FROM DUAL
                WHERE NOT EXISTS (SELECT 1 FROM absensi WHERE siswa_id = %s AND tanggal = %s)
            """, (sid, tgl.isoformat(), KETERANGAN_ALPA, sid, tgl.isoformat()))
            baru += max(cursor.rowcount, 0)
        conn.commit()
        return baru
    except Exception as e:  # jangan sampai thread/permintaan web ikut mati
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[ERROR AUTO ALPA]: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()


def _loop():
    while True:
        try:
            with _sapu_lock:
                jalankan_auto_alpa()
        except Exception as e:
            print(f"[ERROR AUTO ALPA LOOP]: {e}")
        _time.sleep(INTERVAL_DETIK)


def pastikan_penjadwal_jalan():
    """Start thread latar belakang sekali per proses (aman dipanggil berulang)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, name='auto-alpa', daemon=True)
        _thread.start()
