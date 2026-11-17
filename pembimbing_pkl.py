"""Modul PEMBIMBING PKL (guru pembimbing dari sekolah) — khusus & terpisah.

* Semua route ada di blueprint `pkl` dengan awalan URL `/pkl`.
* Semua template ada di `templates/pkl/` (tidak berbagi file dengan
  pembimbing industri / admin).
* Mode PEMANTAU (read-only): tidak ada tombol ubah / hapus / setujui.
* Setiap query dibatasi ke siswa yang DIBIMBING akun ini, yaitu
  `siswa.pembimbing_pkl_id = users.id` (diatur oleh Admin lewat
  menu Kelola Pembimbing -> Siswa Bimbingan). Siswa lain, termasuk yang
  satu sekolah, tidak terlihat dan akses langsung lewat URL -> 403.
"""
from functools import wraps

import mysql.connector
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

from waktu import sekarang_wib
from config import get_db_connection

ROLE_PKL = 'pembimbing_pkl'

pkl_bp = Blueprint('pkl', __name__, url_prefix='/pkl')


# ------------------------------------------------------------------ helper
def pkl_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('logged_in') or session.get('role') != ROLE_PKL:
            flash('Akses ditolak. Halaman khusus Pembimbing PKL.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def _uid():
    return session.get('user_id')


def _punya_siswa(cursor, siswa_id):
    """True bila siswa tsb dibimbing oleh akun yang sedang login."""
    cursor.execute(
        "SELECT 1 FROM siswa s WHERE s.id = %s AND s.pembimbing_pkl_id = %s LIMIT 1",
        (siswa_id, _uid()))
    return cursor.fetchone() is not None


def _db():
    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return None, None
    return conn, conn.cursor(dictionary=True)


@pkl_bp.app_template_filter('pkl_tgl')
def pkl_tgl(nilai):
    """Tanggal ramah-baca (dd-mm-yyyy); toleran terhadap date/datetime/str."""
    if not nilai:
        return '-'
    if hasattr(nilai, 'strftime'):
        return nilai.strftime('%d-%m-%Y')
    teks = str(nilai)[:10]
    try:
        y, m, d = teks.split('-')
        return f'{d}-{m}-{y}'
    except ValueError:
        return teks


@pkl_bp.app_template_filter('pkl_jam')
def pkl_jam(nilai):
    if not nilai:
        return '-'
    if hasattr(nilai, 'strftime'):
        return nilai.strftime('%H:%M')
    return str(nilai)[11:16] or '-'


# --------------------------------------------------------------- dashboard
@pkl_bp.route('/')
@pkl_bp.route('/dashboard')
@pkl_required
def dashboard():
    conn, cursor = _db()
    if not conn:
        return redirect(url_for('login'))
    hari_ini = sekarang_wib().date().isoformat()
    try:
        cursor.execute("SELECT COUNT(*) AS n FROM siswa s WHERE s.pembimbing_pkl_id = %s", (_uid(),))
        total_siswa = cursor.fetchone()['n']

        cursor.execute("""
            SELECT COUNT(*) AS n
            FROM laporan_harian l JOIN siswa s ON l.siswa_id = s.id
            WHERE s.pembimbing_pkl_id = %s AND l.status_validasi = 'Pending'
        """, (_uid(),))
        laporan_pending = cursor.fetchone()['n']

        # Status tiap siswa bimbingan HARI INI
        cursor.execute("""
            SELECT s.id, u.nama, s.nisn, s.kelas_jurusan,
                   a.status, a.keterangan, a.created_at
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN absensi a ON a.siswa_id = s.id AND a.tanggal = %s
            WHERE s.pembimbing_pkl_id = %s
            ORDER BY u.nama ASC
        """, (hari_ini, _uid()))
        hari_ini_list = cursor.fetchall()
    except mysql.connector.Error as e:
        flash(f'Gagal memuat data: {e}', 'danger')
        total_siswa, laporan_pending, hari_ini_list = 0, 0, []
    finally:
        cursor.close()
        conn.close()

    rekap = {'Hadir': 0, 'Izin': 0, 'Sakit': 0, 'Alpa': 0, 'Belum': 0}
    for r in hari_ini_list:
        rekap[r['status'] if r['status'] in rekap else 'Belum'] += 1

    return render_template('pkl/dashboard.html', total_siswa=total_siswa,
                           laporan_pending=laporan_pending, rekap=rekap,
                           hari_ini_list=hari_ini_list, hari_ini=hari_ini)


# ------------------------------------------------------------------- siswa
@pkl_bp.route('/siswa')
@pkl_required
def siswa():
    filter_nama = request.args.get('nama', '').strip()
    filter_nisn = request.args.get('nisn', '').strip()

    conn, cursor = _db()
    if not conn:
        return redirect(url_for('pkl.dashboard'))
    try:
        sql = """
            SELECT s.id, s.nisn, s.kelas_jurusan, s.tgl_mulai_pkl, s.tgl_selesai_pkl,
                   u.nama, u.is_active, k.nama AS nama_sekolah,
                   (SELECT COUNT(*) FROM absensi a WHERE a.siswa_id = s.id AND a.status = 'Hadir') AS hadir,
                   (SELECT COUNT(*) FROM absensi a WHERE a.siswa_id = s.id AND a.status = 'Izin')  AS izin,
                   (SELECT COUNT(*) FROM absensi a WHERE a.siswa_id = s.id AND a.status = 'Sakit') AS sakit,
                   (SELECT COUNT(*) FROM absensi a WHERE a.siswa_id = s.id AND a.status = 'Alpa')  AS alpa
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN sekolah k ON s.sekolah_id = k.id
            WHERE s.pembimbing_pkl_id = %s
        """
        params = [_uid()]
        if filter_nama:
            sql += " AND u.nama LIKE %s"
            params.append(f"%{filter_nama}%")
        if filter_nisn:
            sql += " AND s.nisn LIKE %s"
            params.append(f"%{filter_nisn}%")
        sql += " ORDER BY u.nama ASC"
        cursor.execute(sql, tuple(params))
        siswa_list = cursor.fetchall()
    except mysql.connector.Error as e:
        flash(f'Terjadi kesalahan saat mengambil data: {e}', 'danger')
        siswa_list = []
    finally:
        cursor.close()
        conn.close()
    return render_template('pkl/siswa.html', siswa_list=siswa_list,
                           filter_nama=filter_nama, filter_nisn=filter_nisn)


@pkl_bp.route('/siswa/<int:siswa_id>')
@pkl_required
def siswa_detail(siswa_id):
    conn, cursor = _db()
    if not conn:
        return redirect(url_for('pkl.siswa'))
    try:
        if not _punya_siswa(cursor, siswa_id):
            abort(403)

        cursor.execute("""
            SELECT s.*, u.nama, u.username, u.is_active, k.nama AS nama_sekolah
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN sekolah k ON s.sekolah_id = k.id
            WHERE s.id = %s
        """, (siswa_id,))
        siswa_row = cursor.fetchone()

        cursor.execute("""
            SELECT COALESCE(SUM(status = 'Hadir'), 0) AS hadir,
                   COALESCE(SUM(status = 'Izin'), 0)  AS izin,
                   COALESCE(SUM(status = 'Sakit'), 0) AS sakit,
                   COALESCE(SUM(status = 'Alpa'), 0)  AS alpa
            FROM absensi WHERE siswa_id = %s
        """, (siswa_id,))
        absensi = cursor.fetchone()

        cursor.execute("""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(status_validasi = 'Disetujui'), 0) AS disetujui,
                   COALESCE(SUM(status_validasi = 'Pending'), 0)   AS pending,
                   COALESCE(SUM(status_validasi = 'Revisi'), 0)    AS revisi
            FROM laporan_harian WHERE siswa_id = %s
        """, (siswa_id,))
        laporan = cursor.fetchone()

        cursor.execute("SELECT * FROM absensi WHERE siswa_id = %s ORDER BY tanggal DESC LIMIT 10", (siswa_id,))
        absensi_terbaru = cursor.fetchall()

        cursor.execute("""
            SELECT id, tanggal, deskripsi_kegiatan, status_validasi
            FROM laporan_harian WHERE siswa_id = %s ORDER BY tanggal DESC LIMIT 10
        """, (siswa_id,))
        laporan_terbaru = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return render_template('pkl/siswa_detail.html', siswa=siswa_row, absensi=absensi,
                           laporan=laporan, absensi_terbaru=absensi_terbaru,
                           laporan_terbaru=laporan_terbaru)


# ----------------------------------------------------------------- laporan
@pkl_bp.route('/laporan')
@pkl_required
def laporan():
    filter_status = request.args.get('status', '').strip()
    filter_siswa = request.args.get('siswa_id', type=int)

    conn, cursor = _db()
    if not conn:
        return redirect(url_for('pkl.dashboard'))
    try:
        sql = """
            SELECT l.id, l.tanggal, l.deskripsi_kegiatan, l.status_validasi, l.created_at,
                   u.nama AS nama_siswa, s.kelas_jurusan
            FROM laporan_harian l
            JOIN siswa s ON l.siswa_id = s.id
            JOIN users u ON s.user_id = u.id
            WHERE s.pembimbing_pkl_id = %s
        """
        params = [_uid()]
        if filter_status in ('Pending', 'Disetujui', 'Revisi'):
            sql += " AND l.status_validasi = %s"
            params.append(filter_status)
        if filter_siswa:
            sql += " AND l.siswa_id = %s"
            params.append(filter_siswa)
        sql += " ORDER BY l.tanggal DESC, l.id DESC"
        cursor.execute(sql, tuple(params))
        laporan_list = cursor.fetchall()

        cursor.execute("""
            SELECT s.id, u.nama FROM siswa s JOIN users u ON s.user_id = u.id
            WHERE s.pembimbing_pkl_id = %s ORDER BY u.nama ASC
        """, (_uid(),))
        dft_siswa = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return render_template('pkl/laporan.html', laporan_list=laporan_list, dft_siswa=dft_siswa,
                           filter_status=filter_status, filter_siswa=filter_siswa)


@pkl_bp.route('/laporan/<int:laporan_id>')
@pkl_required
def laporan_detail(laporan_id):
    conn, cursor = _db()
    if not conn:
        return redirect(url_for('pkl.laporan'))
    try:
        cursor.execute("""
            SELECT l.*, u.nama AS nama_siswa, s.nisn, s.kelas_jurusan, k.nama AS nama_sekolah
            FROM laporan_harian l
            JOIN siswa s ON l.siswa_id = s.id
            JOIN users u ON s.user_id = u.id
            LEFT JOIN sekolah k ON s.sekolah_id = k.id
            WHERE l.id = %s AND s.pembimbing_pkl_id = %s
        """, (laporan_id, _uid()))
        laporan_row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    if not laporan_row:
        abort(403)
    return render_template('pkl/laporan_detail.html', laporan=laporan_row)


# ----------------------------------------------------------------- absensi
@pkl_bp.route('/absensi')
@pkl_required
def absensi():
    filter_tanggal = request.args.get('tanggal', '').strip()
    filter_status = request.args.get('status', '').strip()
    filter_nama = request.args.get('nama_siswa', '').strip()

    conn, cursor = _db()
    if not conn:
        return redirect(url_for('pkl.dashboard'))
    try:
        sql = """
            SELECT a.*, u.nama AS nama_siswa, s.kelas_jurusan
            FROM absensi a
            JOIN siswa s ON a.siswa_id = s.id
            JOIN users u ON s.user_id = u.id
            WHERE s.pembimbing_pkl_id = %s
        """
        params = [_uid()]
        if filter_tanggal:
            sql += " AND a.tanggal = %s"
            params.append(filter_tanggal)
        if filter_status in ('Hadir', 'Izin', 'Sakit', 'Alpa'):
            sql += " AND a.status = %s"
            params.append(filter_status)
        if filter_nama:
            sql += " AND u.nama LIKE %s"
            params.append(f"%{filter_nama}%")
        sql += " ORDER BY a.tanggal DESC, u.nama ASC"
        cursor.execute(sql, tuple(params))
        absensi_list = cursor.fetchall()
    except mysql.connector.Error as e:
        flash(f'Terjadi kesalahan saat mengambil data: {e}', 'danger')
        absensi_list = []
    finally:
        cursor.close()
        conn.close()
    return render_template('pkl/absensi.html', absensi_list=absensi_list,
                           filter_tanggal=filter_tanggal, filter_status=filter_status,
                           filter_nama=filter_nama)
