import os
import time
import uuid
import io
import hmac
import re
import secrets
from functools import wraps

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from datetime import date, datetime, timedelta, timezone

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    abort,
    jsonify,
    send_from_directory,
    session,
    url_for,
    send_file
)
import mysql.connector
import pyotp
import segno
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import Config, get_db_connection
from waktu import WIB, now_wib, sekarang_wib, today_wib
from auto_alpa import jalankan_auto_alpa, pastikan_penjadwal_jalan
from pembimbing_pkl import pkl_bp

app = Flask(__name__)
app.config.from_object(Config)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Login bertahan 7 hari walau browser ditutup, lalu otomatis logout.
MASA_LOGIN = timedelta(days=7)
app.config['PERMANENT_SESSION_LIFETIME'] = MASA_LOGIN
app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')

# Modul Pembimbing PKL dipisah total (route di pembimbing_pkl.py, template di templates/pkl/)
app.register_blueprint(pkl_bp)

# =========================================================
# KEAMANAN: CSRF, header respons, pembatasan percobaan login
# =========================================================
def csrf_token():
    """Token CSRF per-sesi; dipakai di template lewat {{ csrf_token() }}."""
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(32)
    return session['_csrf']

app.jinja_env.globals['csrf_token'] = csrf_token

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('error.html', 
                           code="403", 
                           title="Akses Ditolak", 
                           message="Anda tidak memiliki hak akses untuk membuka halaman atau file ini."), 403

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', 
                           code="404", 
                           title="Halaman Tidak Ditemukan", 
                           message="Halaman atau file yang Anda cari tidak ditemukan atau telah dipindahkan."), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', 
                           code="500", 
                           title="Kesalahan Server", 
                           message="Terjadi masalah internal pada server. Silakan coba beberapa saat lagi."), 500


def mulai_sesi_login():
    """Tandai sesi sebagai permanen (cookie tetap ada setelah browser ditutup) + catat waktu login."""
    session.permanent = True
    session['login_at'] = time.time()


@app.before_request
def batasi_masa_login():
    """Logout otomatis tepat 7 hari setelah login (bukan diperpanjang tiap request)."""
    if session.get('logged_in') is True:
        mulai = session.get('login_at')
        if mulai is None:
            # sesi lama sebelum perbaikan ini: mulai hitung dari sekarang
            mulai_sesi_login()
        elif time.time() - mulai > MASA_LOGIN.total_seconds():
            session.clear()
            flash('Sesi login Anda telah berakhir (7 hari). Silakan login kembali.', 'warning')
            if request.method == 'GET' and request.endpoint not in ('login', 'static'):
                return redirect(url_for('login'))


@app.before_request
def lindungi_csrf():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None
    dikirim = request.form.get('csrf_token') or request.headers.get('X-CSRFToken') or ''
    asli = session.get('_csrf', '')
    if asli and hmac.compare_digest(dikirim, asli):
        return None
    if request.headers.get('X-CSRFToken') is not None or request.is_json:
        return jsonify({'status': 'error', 'message': 'Token keamanan tidak valid.'}), 400
    flash('Sesi formulir kedaluwarsa. Silakan muat ulang halaman dan coba lagi.', 'danger')
    return redirect(request.referrer or url_for('login'))


@app.after_request
def tambah_header_keamanan(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'same-origin')
    return resp


# Pembatasan login sederhana (in-memory, per proses): 5 gagal / 10 menit per IP+username
LOGIN_MAX_GAGAL = 5
LOGIN_JENDELA_DETIK = 600
_login_gagal = {}

def _kunci_login(username):
    return f"{request.remote_addr}|{username.lower()}"

def login_terkunci(username):
    sekarang = time.time()
    daftar = [t for t in _login_gagal.get(_kunci_login(username), []) if sekarang - t < LOGIN_JENDELA_DETIK]
    _login_gagal[_kunci_login(username)] = daftar
    return len(daftar) >= LOGIN_MAX_GAGAL

def catat_login_gagal(username):
    _login_gagal.setdefault(_kunci_login(username), []).append(time.time())

def reset_login_gagal(username):
    _login_gagal.pop(_kunci_login(username), None)

# =========================================================
# PERBAIKAN: Tentukan Absolute Path & Ekstensi File yang Diizinkan
# =========================================================
# Menyimpan direktori upload secara absolut di folder static/uploads/profil
# Railway: disk container bersifat sementara (terhapus tiap deploy/restart). Agar foto TIDAK hilang,
# pasang Railway Volume; path mount-nya otomatis tersedia di RAILWAY_VOLUME_MOUNT_PATH
# (atau isi manual lewat variabel UPLOAD_DIR). Tanpa volume -> memakai folder lokal seperti sebelumnya.
_VOLUME_DIR = os.environ.get('UPLOAD_DIR') or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
if _VOLUME_DIR:
    app.config['UPLOAD_FOLDER'] = os.path.join(_VOLUME_DIR, 'uploads')
    UPLOAD_FOLDER_PROFIL = os.path.join(_VOLUME_DIR, 'uploads', 'profil')
else:
    UPLOAD_FOLDER_PROFIL = os.path.join(app.root_path, 'static', 'uploads', 'profil')
app.config['UPLOAD_FOLDER_PROFIL'] = UPLOAD_FOLDER_PROFIL
os.makedirs(UPLOAD_FOLDER_PROFIL, exist_ok=True)
if app.config.get('UPLOAD_FOLDER'):
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Login admin wajib kode 6 digit dari Google Authenticator (TOTP). Set env ADMIN_2FA=0 untuk mematikan.
ADMIN_2FA_WAJIB = os.environ.get('ADMIN_2FA', '1') != '0'
BATAS_2FA_DETIK = 300   # waktu maksimal antara password benar -> kode 2FA dimasukkan

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_logged_in():
    return 'logged_in' in session and session['logged_in'] is True


# =========================================================
# ROLE & SCOPE SEKOLAH
# ---------------------------------------------------------
# admin              : akses penuh semua sekolah + kelola sekolah/pembimbing
#                      + menetapkan siswa bimbingan tiap pembimbing_pkl
# pembimbing_industri: (belum dibatasi) melihat semua siswa
# pembimbing_pkl     : TIDAK memakai route di file ini. Modul terpisah di
#                      pembimbing_pkl.py (/pkl/...) + templates/pkl/, mode
#                      pemantau, hanya siswa dengan siswa.pembimbing_pkl_id = dirinya
# siswa              : hanya data miliknya sendiri
# =========================================================
STAFF_ROLES = ('admin', 'pembimbing_industri')


def is_staff():
    """True jika login sebagai admin / pembimbing_industri.

    pembimbing_pkl SENGAJA tidak termasuk: ia punya modul sendiri (blueprint `pkl`).
    """
    return is_logged_in() and session.get('role') in STAFF_ROLES


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in() or session.get('role') != 'admin':
            flash('Akses ditolak. Halaman khusus Admin.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def scope_sekolah(alias='s'):
    """Potongan SQL pembatas data untuk route staf di file ini.

    Admin & pembimbing_industri tidak dibatasi -> ("", []). Pembimbing PKL tidak
    pernah sampai sini (bukan staf; modulnya ada di pembimbing_pkl.py). Bila suatu
    saat role lain lolos, hasilnya dikosongkan (fail closed).
    """
    if session.get('role') not in ('admin', 'pembimbing_industri'):
        return " AND 1=0", []
    return "", []


def _cek_scope(query, param):
    """Jalankan query cek kepemilikan memakai scope sekolah. True = boleh."""
    sql, params = scope_sekolah('s')
    if not sql:
        return True
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    try:
        cursor.execute(query + sql + " LIMIT 1", (param, *params))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()


def akses_siswa(siswa_id):
    return _cek_scope("SELECT 1 FROM siswa s WHERE s.id = %s", siswa_id)


def akses_laporan(laporan_id):
    return _cek_scope(
        "SELECT 1 FROM laporan_harian l JOIN siswa s ON l.siswa_id = s.id WHERE l.id = %s",
        laporan_id)


def akses_pengajuan(pengajuan_id):
    return _cek_scope(
        "SELECT 1 FROM pengajuan_absensi p JOIN siswa s ON p.siswa_id = s.id WHERE p.id = %s",
        pengajuan_id)


def daftar_sekolah_boleh(cursor):
    """Sekolah yang boleh dipilih user saat ini pada form siswa (admin / industri: semua)."""
    cursor.execute("SELECT id, nama FROM sekolah ORDER BY nama")
    return cursor.fetchall()

# =========================================================
# AUTO-ALPA jam 15:00 WIB — logika lengkap ada di auto_alpa.py
# ---------------------------------------------------------
# Berjalan untuk SEMUA siswa meskipun tidak login (thread latar belakang tiap
# 60 detik + CLI `flask --app app auto-alpa`). Fungsi di bawah dipertahankan
# agar pemanggilnya (dashboard/absensi/pengajuan siswa) tidak perlu diubah;
# kini ia hanya memicu pengecekan yang sama untuk siswa tsb.
# =========================================================
def cek_dan_set_alpa_otomatis(siswa_id, today_str=None):
    jalankan_auto_alpa(siswa_id=siswa_id)


def tolak_jika_hari_minggu(kegiatan):
    """Hari Minggu libur PKL: siswa tidak bisa absen / mengajukan izin / kirim laporan.

    Mengembalikan response redirect bila hari ini Minggu (WIB), selain itu None.
    """
    if today_wib().weekday() == 6:
        flash(f'Hari Minggu adalah hari libur PKL. Anda tidak dapat {kegiatan} pada hari Minggu.', 'warning')
        return redirect(url_for('dashboard_siswa'))
    return None


BULAN_ID = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
            'Agustus', 'September', 'Oktober', 'November', 'Desember']


def tgl_indo(v):
    """2026-11-17 -> '17 November 2026' (tanpa tergantung locale server)."""
    if isinstance(v, str):
        try:
            v = datetime.strptime(v[:10], '%Y-%m-%d')
        except ValueError:
            return v
    if v is None or v == '':
        return '-'
    return f"{v.day} {BULAN_ID[v.month - 1]} {v.year}"


app.jinja_env.filters['tgl_indo'] = tgl_indo


def _ke_tanggal(v):
    return v.date() if isinstance(v, datetime) else v


JAM_TUTUP_PRESENSI = datetime.strptime("15:00:00", "%H:%M:%S").time()


def presensi_ditutup():
    """True bila sudah pukul 15:00 WIB atau lebih.

    Batas ini dicek LANGSUNG di setiap route siswa (presensi, pengajuan terlambat,
    izin/sakit), tidak bergantung pada ada-tidaknya baris Alpa di database, supaya
    tidak ada celah (mis. siswa di luar periode PKL, pengajuan terlambat yang baru di-ACC).
    """
    return now_wib().time() >= JAM_TUTUP_PRESENSI


@app.before_request
def _pastikan_auto_alpa_jalan():
    # Murah: hanya memeriksa thread sudah hidup atau belum (mis. di bawah gunicorn).
    pastikan_penjadwal_jalan()


@app.cli.command('auto-alpa')
def cli_auto_alpa():
    """Catat Alpa untuk siswa yang belum absen (untuk cron / dijalankan manual)."""
    print(f"Alpa baru dicatat: {jalankan_auto_alpa()}")


def pastikan_skema():
    """Tambahkan kolom siswa.pembimbing_pkl_id bila belum ada (lihat migrations/*.sql)."""
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM siswa LIKE 'pembimbing_pkl_id'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE siswa ADD COLUMN pembimbing_pkl_id INT NULL, "
                           "ADD INDEX idx_siswa_pembimbing_pkl (pembimbing_pkl_id)")
            conn.commit()
            print("[MIGRASI] kolom siswa.pembimbing_pkl_id ditambahkan")
    except Exception as e:
        print(f"[MIGRASI] gagal memeriksa/menambah pembimbing_pkl_id: {e}")
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hari_libur (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tanggal DATE NOT NULL,
                keterangan VARCHAR(150) NOT NULL,
                sekolah_id INT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_hari_libur_tanggal (tanggal)
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"[MIGRASI] gagal membuat tabel hari_libur: {e}")
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pengumuman_dibaca (
                user_id INT NOT NULL,
                pengumuman_id INT NOT NULL,
                dibaca_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, pengumuman_id)
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"[MIGRASI] gagal membuat tabel pengumuman_dibaca: {e}")
    try:
        cursor.execute("SHOW COLUMNS FROM users LIKE 'totp_secret'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64) NULL")
            conn.commit()
            print("[MIGRASI] kolom users.totp_secret ditambahkan")
    except Exception as e:
        print(f"[MIGRASI] gagal memeriksa/menambah totp_secret: {e}")
    finally:
        cursor.close()
        conn.close()

@app.context_processor
def inject_siswa():
    if is_logged_in() and session.get('role') == 'siswa' and session.get('siswa_id'):
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT s.*, u.nama, u.username, k.nama AS sekolah, k.nama AS nama_sekolah
                FROM siswa s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN sekolah k ON s.sekolah_id = k.id
                WHERE s.id = %s
            """, (session['siswa_id'],))
            siswa_data = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(siswa=siswa_data)
        except Exception:
            return dict(siswa=None)
    return dict(siswa=None)

@app.context_processor
def inject_pengumuman():
    """Isi lonceng pengumuman untuk SEMUA halaman yang punya lonceng (bukan hanya dashboard siswa).

    Status 'sudah dibaca' disimpan di database per user, jadi tidak hilang saat ganti
    browser/perangkat atau data browser dibersihkan.
    """
    kosong = dict(pengumuman_list=[], pengumuman_belum_dibaca=0)
    if not is_logged_in() or not session.get('user_id'):
        return kosong
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        sekolah_id = session.get('sekolah_id')
        if session.get('role') == 'siswa' and session.get('siswa_id'):
            cursor.execute("SELECT sekolah_id FROM siswa WHERE id = %s", (session['siswa_id'],))
            baris = cursor.fetchone()
            sekolah_id = baris['sekolah_id'] if baris else None
        cursor.execute("""
            SELECT p.*, (d.pengumuman_id IS NOT NULL) AS dibaca
            FROM pengumuman_pembimbing p
            LEFT JOIN pengumuman_dibaca d
                   ON d.pengumuman_id = p.id AND d.user_id = %s
            WHERE p.sekolah_id IS NULL OR p.sekolah_id = %s
            ORDER BY p.id DESC LIMIT 30
        """, (session['user_id'], sekolah_id))
        daftar = cursor.fetchall()
        cursor.close()
        return dict(pengumuman_list=daftar,
                    pengumuman_belum_dibaca=sum(1 for x in daftar if not x['dibaca']))
    except Exception:
        return kosong
    finally:
        if conn:
            conn.close()


@app.route('/pengumuman/tandai-dibaca', methods=['POST'])
def tandai_pengumuman_dibaca():
    if not is_logged_in():
        return jsonify({'status': 'error'}), 401
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in data.get('ids', []) if str(i).isdigit()][:100]
    if ids:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.executemany(
                "INSERT IGNORE INTO pengumuman_dibaca (user_id, pengumuman_id) VALUES (%s, %s)",
                [(session['user_id'], i) for i in ids])
            conn.commit()
        finally:
            cursor.close()
            conn.close()
    return jsonify({'status': 'ok'})


@app.context_processor
def inject_notif_staff():
    """Angka badge sidebar (izin/sakit & laporan pending) untuk SEMUA halaman staf.

    Sebelumnya angka ini hanya dikirim oleh route dashboard, sehingga di halaman lain
    badge tidak muncul / error.
    """
    notif = dict(notif_pengajuan=0, notif_laporan=0)
    if is_staff():
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            sc, scp = scope_sekolah('s')
            cursor.execute(
                "SELECT COUNT(*) FROM pengajuan_absensi p JOIN siswa s ON p.siswa_id = s.id "
                "WHERE p.status_pengajuan = 'Pending'" + sc, tuple(scp))
            notif['notif_pengajuan'] = cursor.fetchone()[0] or 0
            cursor.execute(
                "SELECT COUNT(*) FROM laporan_harian l JOIN siswa s ON l.siswa_id = s.id "
                "WHERE l.status_validasi = 'Pending'" + sc, tuple(scp))
            notif['notif_laporan'] = cursor.fetchone()[0] or 0
            cursor.close()
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
    return notif


@app.route('/')
def index():
    if is_logged_in():
        role = session.get('role')
        if role == 'siswa':
            return redirect(url_for('dashboard_siswa'))
        elif role == 'admin':
            return redirect(url_for('dashboard_admin'))
        elif role == 'pembimbing_pkl':
            return redirect(url_for('pkl.dashboard'))
        elif role == 'pembimbing_industri':
            return redirect(url_for('dashboard_pembimbing'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Username dan password wajib diisi!', 'danger')
            return render_template('login.html')

        if login_terkunci(username):
            flash('Terlalu banyak percobaan login. Coba lagi dalam 10 menit.', 'danger')
            return render_template('login.html')

        conn = get_db_connection()
        if not conn:
            flash('Gagal terhubung ke server database.', 'danger')
            return render_template('login.html')

        cursor = conn.cursor(dictionary=True)
        try:
            query = "SELECT * FROM users WHERE username = %s"
            cursor.execute(query, (username,))
            user = cursor.fetchone()

            if user and check_password_hash(user['password'], password):
                # -----------------------------------------------------------------
                # 📌 PENGECEKAN STATUS AKUN (is_active)
                # Jika is_active == 0, blokir akses login dan tampilkan notifikasi.
                # -----------------------------------------------------------------
                if user.get('is_active') == 0:
                    flash('Akun Anda telah dinonaktifkan oleh Pembimbing. Silakan hubungi Pembimbing PKL Anda.', 'danger')
                    cursor.close()
                    conn.close()
                    return render_template('login.html')

                # Pembimbing PKL wajib terikat ke satu sekolah (dasar pembatasan data)
                if user['role'] == 'pembimbing_pkl' and not user.get('sekolah_id'):
                    flash('Akun Pembimbing PKL Anda belum dikaitkan dengan sekolah. Hubungi Admin.', 'danger')
                    cursor.close()
                    conn.close()
                    return render_template('login.html')

                # ADMIN: password benar belum cukup -> lanjut ke verifikasi kode Authenticator
                if user['role'] == 'admin' and ADMIN_2FA_WAJIB:
                    session.clear()
                    session['pending_2fa_uid'] = user['id']
                    session['pending_2fa_at'] = time.time()
                    cursor.close()
                    conn.close()
                    return redirect(url_for('login_2fa'))

                # Membersihkan frasa (Guru) atau (Pembimbing) dari nama
                nama_bersih = user['nama'].replace(' (Guru)', '').replace('(Guru)', '').replace(' (Pembimbing)', '').replace('(Pembimbing)', '').strip()

                reset_login_gagal(username)
                session.clear()  # cegah session fixation
                mulai_sesi_login()
                session['logged_in'] = True
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['nama'] = nama_bersih  # Tersimpan bersih di session
                session['role'] = user['role']
                session['sekolah_id'] = user.get('sekolah_id')

                if user['role'] == 'siswa':
                    cursor.execute("SELECT id FROM siswa WHERE user_id = %s", (user['id'],))
                    siswa_data = cursor.fetchone()
                    if siswa_data:
                        session['siswa_id'] = siswa_data['id']

                # Redirect sesuai role
                if user['role'] == 'siswa':
                    return redirect(url_for('dashboard_siswa'))
                elif user['role'] == 'admin':
                    return redirect(url_for('dashboard_admin'))
                elif user['role'] == 'pembimbing_pkl':
                    return redirect(url_for('pkl.dashboard'))
                else:
                    return redirect(url_for('dashboard_pembimbing'))
            else:
                catat_login_gagal(username)
                flash('Username atau password salah!', 'danger')
        except mysql.connector.Error as e:
            flash(f'Error Database: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('login.html')

@app.route('/login/2fa', methods=['GET', 'POST'])
def login_2fa():
    """Langkah ke-2 login admin: kode TOTP (Google Authenticator / Authy / dll).

    Admin yang belum punya secret diminta memindai QR dulu (pendaftaran sekali saja).
    """
    uid = session.get('pending_2fa_uid')
    if not uid or time.time() - session.get('pending_2fa_at', 0) > BATAS_2FA_DETIK:
        session.clear()
        flash('Sesi verifikasi berakhir. Silakan login ulang.', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke server database.', 'danger')
        return redirect(url_for('login'))
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE id = %s AND role = 'admin'", (uid,))
        user = cursor.fetchone()
        if not user or user.get('is_active') == 0:
            session.clear()
            return redirect(url_for('login'))

        secret = user.get('totp_secret')
        mode_setup = not secret
        if mode_setup:
            secret = session.get('pending_2fa_secret') or pyotp.random_base32()
            session['pending_2fa_secret'] = secret

        kunci = '2fa:' + user['username']
        if request.method == 'POST':
            if login_terkunci(kunci):
                flash('Terlalu banyak kode salah. Coba lagi dalam 10 menit.', 'danger')
            else:
                kode = re.sub(r'\D', '', request.form.get('kode', ''))
                if len(kode) == 6 and pyotp.TOTP(secret).verify(kode, valid_window=1):
                    if mode_setup:
                        cursor.execute("UPDATE users SET totp_secret = %s WHERE id = %s", (secret, user['id']))
                        conn.commit()
                    reset_login_gagal(kunci)
                    reset_login_gagal(user['username'])
                    session.clear()  # cegah session fixation
                    mulai_sesi_login()
                    session['logged_in'] = True
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['nama'] = user['nama'].replace(' (Guru)', '').replace('(Guru)', '').replace(' (Pembimbing)', '').replace('(Pembimbing)', '').strip()
                    session['role'] = 'admin'
                    session['sekolah_id'] = user.get('sekolah_id')
                    return redirect(url_for('dashboard_admin'))
                catat_login_gagal(kunci)
                flash('Kode salah atau sudah kedaluwarsa. Periksa jam HP Anda lalu coba lagi.', 'danger')

        qr_uri = None
        if mode_setup:
            uri = pyotp.TOTP(secret).provisioning_uri(name=user['username'], issuer_name='E-Jurnal PKL')
            qr_uri = segno.make(uri, error='m').svg_data_uri(scale=5, border=2)
        return render_template('login_2fa.html', mode_setup=mode_setup, qr_uri=qr_uri,
                               secret=secret if mode_setup else None, username=user['username'])
    finally:
        cursor.close()
        conn.close()


@app.route('/dashboard/siswa')
def dashboard_siswa():
    if not is_logged_in() or session.get('role') != 'siswa':
        flash('Akses ditolak. Silakan login sebagai Siswa.', 'danger')
        return redirect(url_for('login'))

    siswa_id = session.get('siswa_id')
    waktu_lokal = now_wib()
    today_str = waktu_lokal.strftime('%Y-%m-%d')
    jam_sekarang = waktu_lokal.time()

    # =========================================================================
    # JALANKAN PENGECEKAN AUTO ALPA (Siswa > 15:00 WIB yang Belum Absen)
    # =========================================================================
    cek_dan_set_alpa_otomatis(siswa_id, today_str)

    conn = get_db_connection()
    if conn is None:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('login'))

    cursor = conn.cursor(dictionary=True)

    # 1. Detail Data Siswa
    cursor.execute("""
        SELECT s.*, u.nama, u.username, k.nama AS sekolah, k.nama AS nama_sekolah
        FROM siswa s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah k ON s.sekolah_id = k.id
        WHERE s.id = %s
    """, (siswa_id,))
    detail_siswa = cursor.fetchone()

    # 2. Statistik Validasi Laporan Harian
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COALESCE(SUM(CASE WHEN status_validasi = 'Disetujui' THEN 1 ELSE 0 END), 0) as disetujui,
            COALESCE(SUM(CASE WHEN status_validasi = 'Pending' THEN 1 ELSE 0 END), 0) as pending,
            COALESCE(SUM(CASE WHEN status_validasi = 'Revisi' THEN 1 ELSE 0 END), 0) as revisi
        FROM laporan_harian 
        WHERE siswa_id = %s
    """, (siswa_id,))
    stat_laporan = cursor.fetchone()

    # 3. Statistik Presensi Kehadiran Siswa (Akan langsung ter-update jika Alpa bertambah)
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN status = 'Hadir' THEN 1 ELSE 0 END), 0) as hadir,
            COALESCE(SUM(CASE WHEN status = 'Izin' THEN 1 ELSE 0 END), 0) as izin,
            COALESCE(SUM(CASE WHEN status = 'Sakit' THEN 1 ELSE 0 END), 0) as sakit,
            COALESCE(SUM(CASE WHEN status = 'Alpa' THEN 1 ELSE 0 END), 0) as alpa
        FROM absensi 
        WHERE siswa_id = %s
    """, (siswa_id,))
    stat_absensi = cursor.fetchone()

    # 4. Riwayat Laporan Harian Terbaru
    cursor.execute("""
        SELECT *, TIME_FORMAT(created_at, '%H:%i') as jam_kirim 
        FROM laporan_harian 
        WHERE siswa_id = %s 
        ORDER BY created_at DESC LIMIT 5
    """, (siswa_id,))
    laporan_terbaru = cursor.fetchall()

    # 5. Cek absensi hari ini
    cursor.execute("SELECT * FROM absensi WHERE siswa_id = %s AND tanggal = %s", (siswa_id, today_str))
    sudah_absen = cursor.fetchone()

    cursor.close()
    conn.close()

    # Peringatan flash jika belum absen antara jam 09:30 s.d 15:00 WIB
    jam_mulai_notif = datetime.strptime("09:30:00", "%H:%M:%S").time()
    jam_batas_akhir = datetime.strptime("15:00:00", "%H:%M:%S").time()
    
    if today_wib().weekday() == 6:
        pass  # Minggu libur: tanpa peringatan absen
    elif not sudah_absen and (jam_mulai_notif <= jam_sekarang < jam_batas_akhir):
        flash('⚠️ Perhatian: Anda belum melakukan absensi hari ini! Waktu presensi tepat waktu (09.30 WIB) telah terlewat.', 'warning')
    elif sudah_absen and sudah_absen['status'] == 'Alpa':
        flash(' Anda tercatat ALPA untuk hari ini karena tidak melakukan presensi hingga pukul 15:00 WIB.', 'danger')

    return render_template(
        'dashboard_siswa.html',
        siswa=detail_siswa,
        laporan=stat_laporan,
        absensi=stat_absensi,
        laporan_list=laporan_terbaru
    )


@app.route('/dashboard/pembimbing')
def dashboard_pembimbing():
    if not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    # Dashboard Pembimbing Industri & Admin (pembimbing_pkl punya dashboard sendiri: pkl.dashboard)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    sc, scp = scope_sekolah('s')
    scp = tuple(scp)

    cursor.execute("SELECT COUNT(*) as total_siswa FROM siswa s WHERE 1=1" + sc, scp)
    total_siswa = cursor.fetchone()['total_siswa']

    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN l.status_validasi = 'Pending' THEN 1 ELSE 0 END), 0) as pending,
            COALESCE(SUM(CASE WHEN l.status_validasi = 'Disetujui' THEN 1 ELSE 0 END), 0) as disetujui,
            COALESCE(SUM(CASE WHEN l.status_validasi = 'Revisi' THEN 1 ELSE 0 END), 0) as revisi
        FROM laporan_harian l
        JOIN siswa s ON l.siswa_id = s.id
        WHERE 1=1""" + sc, scp)
    stat_laporan = cursor.fetchone()

    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN a.status = 'Hadir' THEN 1 ELSE 0 END), 0) as total_hadir,
            COALESCE(SUM(CASE WHEN a.status = 'Izin' THEN 1 ELSE 0 END), 0) as total_izin,
            COALESCE(SUM(CASE WHEN a.status = 'Sakit' THEN 1 ELSE 0 END), 0) as total_sakit,
            COALESCE(SUM(CASE WHEN a.status = 'Alpa' THEN 1 ELSE 0 END), 0) as total_alpa
        FROM absensi a
        JOIN siswa s ON a.siswa_id = s.id
        WHERE 1=1""" + sc, scp)
    stat_absensi = cursor.fetchone()

    cursor.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN p.status_pengajuan = 'Pending' THEN 1 ELSE 0 END), 0) as pending_izin
        FROM pengajuan_absensi p
        JOIN siswa s ON p.siswa_id = s.id
        WHERE 1=1""" + sc, scp)
    stat_pengajuan = cursor.fetchone()

    cursor.execute("""
        SELECT l.*, u.nama as nama_siswa, s.kelas_jurusan
        FROM laporan_harian l
        JOIN siswa s ON l.siswa_id = s.id
        JOIN users u ON s.user_id = u.id
        WHERE 1=1""" + sc + " ORDER BY l.created_at DESC LIMIT 5", scp)
    laporan_pending = cursor.fetchall()

    cursor.execute("SELECT * FROM pengumuman_pembimbing WHERE sekolah_id IS NULL ORDER BY id DESC LIMIT 1")
    pengumuman = cursor.fetchone()

    cursor.close()
    conn.close()

    # Mengembalikan ke dashboard lama untuk Pembimbing Industri / Admin
    return render_template(
        'dashboard_pembimbing.html',
        total_siswa=total_siswa,
        laporan=stat_laporan,
        absensi=stat_absensi,
        pengajuan=stat_pengajuan,
        laporan_list=laporan_pending,
        pengumuman=pengumuman
    )


# TAMBAHAN: Rute untuk memproses simpan/perbarui pesan pengumuman dari pembimbing
@app.route('/pembimbing/update-pesan', methods=['POST'])
def update_pesan_pembimbing():
    if not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    pesan_baru = request.form.get('pesan', '').strip()

    if pesan_baru:
        conn = get_db_connection()
        cursor = conn.cursor()
        # INSERT pesan baru ke tabel pengumuman_pembimbing
        cursor.execute(
            "INSERT INTO pengumuman_pembimbing (pesan, sekolah_id) VALUES (%s, NULL)",
            (pesan_baru,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Pengumuman baru berhasil dikirim ke siswa!', 'success')
    else:
        flash('Pesan pengumuman tidak boleh kosong!', 'danger')

    return redirect(url_for('dashboard_pembimbing'))
# =========================================================
# ROUTE PROFIL SISWA
# =========================================================
@app.route('/profil', methods=['GET', 'POST'])
def profil():
    if not is_logged_in() or session.get('role') != 'siswa':
        flash('Akses ditolak. Silakan login sebagai Siswa.', 'danger')
        return redirect(url_for('login'))

    siswa_id = session.get('siswa_id')
    user_id = session.get('user_id')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        aksi = request.form.get('aksi')

        # 1. PROSES UPDATE DATA PROFIL LENGKAP & FOTO PROFIL
        if aksi == 'update_profil':
            nama = request.form.get('nama', '').strip()
            tempat_lahir = request.form.get('tempat_lahir', '').strip() or None
            tanggal_lahir = request.form.get('tanggal_lahir', '').strip() or None
            jenis_kelamin = request.form.get('jenis_kelamin', '').strip() or None
            kelas_jurusan = request.form.get('kelas_jurusan', '').strip()
            no_hp = request.form.get('no_hp', '').strip() or None
            email = request.form.get('email', '').strip() or None
            alamat = request.form.get('alamat', '').strip() or None

            if not nama:
                flash('Nama lengkap wajib diisi!', 'danger')
            else:
                try:
                    # Update nama di tabel users & session agar navbar ter-update
                    cursor.execute("UPDATE users SET nama = %s WHERE id = %s", (nama, user_id))
                    session['nama'] = nama

                    # Handling unggah foto profil jika ada file
                    foto_file = request.files.get('foto_profil')
                    foto_nama = None

                    if foto_file and foto_file.filename != '' and allowed_file(foto_file.filename):
                        os.makedirs(app.config['UPLOAD_FOLDER_PROFIL'], exist_ok=True)
                        
                        ext = foto_file.filename.rsplit('.', 1)[1].lower()
                        timestamp = int(time.time())
                        foto_nama = f"foto_profil_{siswa_id}_{timestamp}.{ext}"
                        
                        foto_path = os.path.join(app.config['UPLOAD_FOLDER_PROFIL'], foto_nama)
                        foto_file.save(foto_path)

                    # Update data siswa di database MySQL (TANPA kolom 'nama')
                    if foto_nama:
                        query_siswa = """
                            UPDATE siswa 
                            SET tempat_lahir = %s, tanggal_lahir = %s, jenis_kelamin = %s,
                                kelas_jurusan = %s, no_hp = %s, email = %s, 
                                alamat = %s, foto_profil = %s 
                            WHERE id = %s
                        """
                        cursor.execute(query_siswa, (
                            tempat_lahir, tanggal_lahir, jenis_kelamin,
                            kelas_jurusan, no_hp, email,
                            alamat, foto_nama, siswa_id
                        ))
                    else:
                        query_siswa = """
                            UPDATE siswa 
                            SET tempat_lahir = %s, tanggal_lahir = %s, jenis_kelamin = %s,
                                kelas_jurusan = %s, no_hp = %s, email = %s, 
                                alamat = %s 
                            WHERE id = %s
                        """
                        cursor.execute(query_siswa, (
                            tempat_lahir, tanggal_lahir, jenis_kelamin,
                            kelas_jurusan, no_hp, email,
                            alamat, siswa_id
                        ))

                    conn.commit()
                    flash('Profil berhasil diperbarui!', 'success')
                except mysql.connector.Error as e:
                    conn.rollback()
                    flash(f'Gagal memperbarui profil: {e}', 'danger')

        # 2. PROSES GANTI PASSWORD
        elif aksi == 'ganti_password':
            password_lama = request.form.get('password_lama', '').strip()
            password_baru = request.form.get('password_baru', '').strip()
            konfirmasi_password = request.form.get('konfirmasi_password', '').strip()

            cursor.execute("SELECT password FROM users WHERE id = %s", (user_id,))
            user_data = cursor.fetchone()

            if not user_data or not check_password_hash(user_data['password'], password_lama):
                flash('Password lama / NISN yang Anda masukkan salah!', 'danger')
            elif password_baru != konfirmasi_password:
                flash('Konfirmasi password baru tidak cocok!', 'danger')
            elif len(password_baru) < 6:
                flash('Password baru minimal harus 6 karakter!', 'danger')
            else:
                try:
                    hashed_new_pw = generate_password_hash(password_baru)
                    cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_new_pw, user_id))
                    conn.commit()
                    flash('Password berhasil diganti! Gunakan password baru Anda saat login berikutnya.', 'success')
                except mysql.connector.Error as e:
                    conn.rollback()
                    flash(f'Gagal mengganti password: {e}', 'danger')

        cursor.close()
        conn.close()
        # WAJIB RETURN REDIRECT SETELAH PROSES POST
        return redirect(url_for('profil'))

    # REQUEST GET: Ambil Data Profil Siswa
    cursor.execute("""
        SELECT s.*, u.nama, u.username, k.nama AS sekolah, k.nama AS nama_sekolah
        FROM siswa s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah k ON s.sekolah_id = k.id
        WHERE s.id = %s
    """, (siswa_id,))
    detail_siswa = cursor.fetchone()

    cursor.close()
    conn.close()

    # WAJIB RETURN RENDER TEMPLATE SAAT GET
    return render_template('profil.html', siswa=detail_siswa)

@app.route('/siswa')
def daftar_siswa():
    if not is_staff():
        flash('Akses ditolak. Halaman khusus Pembimbing.', 'danger')
        return redirect(url_for('login'))

    filter_nama = request.args.get('nama', '').strip()
    filter_nisn = request.args.get('nisn', '').strip()
    filter_sekolah = request.args.get('sekolah', '').strip()

    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return render_template('siswa.html', siswa_list=[], filter_nama='', filter_nisn='', filter_sekolah='')

    cursor = conn.cursor(dictionary=True)

    try:
        # Pastikan ada JOIN ke tabel sekolah (k) dan mengambil k.nama AS nama_sekolah
        query = """
            SELECT s.*, u.nama, u.username, u.is_active, k.nama AS nama_sekolah
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN sekolah k ON s.sekolah_id = k.id
            WHERE 1=1
        """
        params = []
        sc, scp = scope_sekolah('s')
        query += sc
        params.extend(scp)

        if filter_nama:
            query += " AND u.nama LIKE %s"
            params.append(f"%{filter_nama}%")

        if filter_nisn:
            query += " AND s.nisn LIKE %s"
            params.append(f"%{filter_nisn}%")

        if filter_sekolah:
            query += " AND k.nama LIKE %s"
            params.append(f"%{filter_sekolah}%")

        query += " ORDER BY u.nama ASC"

        cursor.execute(query, tuple(params))
        siswa_list = cursor.fetchall()

    except mysql.connector.Error as e:
        flash(f'Terjadi kesalahan saat mengambil data: {e}', 'danger')
        siswa_list = []
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'siswa.html',
        siswa_list=siswa_list,
        filter_nama=filter_nama,
        filter_nisn=filter_nisn,
        filter_sekolah=filter_sekolah
    )

@app.route('/siswa/<int:siswa_id>')
def detail_siswa(siswa_id):
    if not is_staff():
        flash('Akses ditolak. Halaman khusus Pembimbing.', 'danger')
        return redirect(url_for('login'))

    if not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # PERBAIKAN: Tambahkan LEFT JOIN ke tabel sekolah (k) untuk mengambil k.nama AS nama_sekolah
    cursor.execute("""
        SELECT s.*, u.nama, u.username, u.is_active, u.created_at, k.nama AS nama_sekolah
        FROM siswa s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah k ON s.sekolah_id = k.id
        WHERE s.id = %s
    """, (siswa_id,))
    siswa = cursor.fetchone()

    if not siswa:
        cursor.close()
        conn.close()
        flash('Data siswa tidak ditemukan!', 'danger')
        return redirect(url_for('daftar_siswa'))

    # Ringkasan Absensi Siswa
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN status = 'Hadir' THEN 1 ELSE 0 END) as hadir,
            SUM(CASE WHEN status = 'Izin' THEN 1 ELSE 0 END) as izin,
            SUM(CASE WHEN status = 'Sakit' THEN 1 ELSE 0 END) as sakit,
            SUM(CASE WHEN status = 'Alpa' THEN 1 ELSE 0 END) as alpa
        FROM absensi WHERE siswa_id = %s
    """, (siswa_id,))
    absensi = cursor.fetchone()

    # Total Laporan
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status_validasi = 'Disetujui' THEN 1 ELSE 0 END) as disetujui,
            SUM(CASE WHEN status_validasi = 'Pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status_validasi = 'Revisi' THEN 1 ELSE 0 END) as revisi
        FROM laporan_harian WHERE siswa_id = %s
    """, (siswa_id,))
    laporan = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template('siswa_detail.html', siswa=siswa, absensi=absensi, laporan=laporan)

import base64

@app.route('/absensi', methods=['GET', 'POST'])
def absensi():
    if not is_logged_in() or session.get('role') != 'siswa':
        flash('Akses ditolak. Silakan login sebagai Siswa.', 'danger')
        return redirect(url_for('login'))

    libur = tolak_jika_hari_minggu('melakukan absensi')
    if libur:
        return libur

    siswa_id = session.get('siswa_id')
    today_str = today_wib().strftime('%Y-%m-%d')

    # Jalankan pengecekan Auto-Alpa jika waktu sudah >= 15:00 WIB
    cek_dan_set_alpa_otomatis(siswa_id, today_str)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # -------------------------------------------------------------------------
    # VALIDASI BATAS WAKTU JAM PRESENSI
    # -------------------------------------------------------------------------
    jam_sekarang = now_wib().time()
    jam_buka = datetime.strptime("09:00:00", "%H:%M:%S").time()
    jam_batas_terlambat = datetime.strptime("09:30:00", "%H:%M:%S").time()

    belum_buka = jam_sekarang < jam_buka
    is_terlambat = jam_sekarang >= jam_batas_terlambat
    presensi_tutup = presensi_ditutup()

    # 1. Cek absensi hari ini (Termasuk jika sudah di-set Alpa otomatis)
    cursor.execute("SELECT * FROM absensi WHERE siswa_id = %s AND tanggal = %s", (siswa_id, today_str))
    absensi_hari_ini = cursor.fetchone()

    # 2. Cek status pengajuan terlambat
    cursor.execute("""
        SELECT * FROM pengajuan_absensi 
        WHERE siswa_id = %s AND tanggal = %s AND jenis = 'Terlambat'
        ORDER BY id DESC LIMIT 1
    """, (siswa_id, today_str))
    pengajuan_terlambat = cursor.fetchone()

    # 3. Cek status pengajuan Izin / Sakit
    cursor.execute("""
        SELECT * FROM pengajuan_absensi 
        WHERE siswa_id = %s AND tanggal = %s AND jenis IN ('Izin', 'Sakit')
        ORDER BY id DESC LIMIT 1
    """, (siswa_id, today_str))
    pengajuan_izin_sakit = cursor.fetchone()

    if request.method == 'POST':
        # CEK 0: Setelah pukul 15:00 WIB presensi & pengajuan terlambat DITUTUP (tanpa kecuali)
        if presensi_tutup and not absensi_hari_ini:
            flash('Presensi telah ditutup pukul 15:00 WIB. Presensi dan pengajuan terlambat tidak dapat dilakukan lagi hari ini.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('absensi'))

        # CEK A: Mencegah absen jika belum pukul 09:00 WIB
        if belum_buka:
            flash('Presensi belum dibuka! Sistem presensi baru dibuka pada pukul 09:00 WIB.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('absensi'))

        # CEK B: Mencegah absen jika sudah ada di tabel absensi (atau sudah Alpa)
        if absensi_hari_ini:
            if absensi_hari_ini['status'] == 'Alpa':
                flash('Waktu presensi telah ditutup (pukul 15:00 WIB). Anda tercatat Alpa untuk hari ini.', 'danger')
            else:
                flash('Anda sudah menyelesaikan presensi untuk hari ini!', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('absensi'))

        # CEK C: Mencegah double pengajuan jika sudah mengajukan Izin / Sakit
        if pengajuan_izin_sakit:
            status_p = pengajuan_izin_sakit['status_pengajuan']
            jenis_p = pengajuan_izin_sakit['jenis']
            flash(f'Anda sudah mengajukan {jenis_p} untuk hari ini (Status: {status_p}).', 'info')
            cursor.close()
            conn.close()
            return redirect(url_for('absensi'))

        keterangan = request.form.get('keterangan', '').strip()
        foto_base64 = request.form.get('foto_base64')
        lokasi = request.form.get('lokasi', '').strip()

        # KONDISI 1: PENGAJUAN TERLAMBAT BARU (Lewat 09:30 WIB)
        if is_terlambat and not pengajuan_terlambat:
            if not keterangan:
                flash('Alasan keterlambatan wajib diisi!', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('absensi'))

            cursor.execute("""
                INSERT INTO pengajuan_absensi 
                (siswa_id, tanggal, jenis, alasan, status_pengajuan, created_at)
                VALUES (%s, %s, 'Terlambat', %s, 'Pending', NOW())
            """, (siswa_id, today_str, keterangan))
            
            conn.commit()
            flash('Pengajuan terlambat telah dikirim ke Pembimbing. Silakan tunggu persetujuan (ACC).', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('absensi'))

        # KONDISI 1b: sudah lewat 09:30 tapi pengajuan terlambat belum di-ACC -> tolak (cegah bypass)
        elif is_terlambat and pengajuan_terlambat['status_pengajuan'] != 'Disetujui':
            if pengajuan_terlambat['status_pengajuan'] == 'Ditolak':
                flash('Pengajuan terlambat Anda ditolak Pembimbing. Anda tidak dapat melakukan presensi.', 'danger')
            else:
                flash('Pengajuan terlambat masih menunggu persetujuan Pembimbing.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('absensi'))

        # KONDISI 2: AMBIL FOTO SELFIE (Pukul 09:00 - 09:30 WIB ATAU Terlambat yang sudah di-ACC)
        else:
            if not foto_base64:
                flash('Gagal! Foto selfie presensi wajib diambil secara langsung.', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('absensi'))

            try:
                filename_db = f"absensi_{siswa_id}_{today_str}_{uuid.uuid4().hex[:6]}.png"
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename_db)
                
                img_data = foto_base64.split(',')[1]
                with open(filepath, "wb") as fh:
                    fh.write(base64.b64decode(img_data))

                if pengajuan_terlambat and pengajuan_terlambat['status_pengajuan'] == 'Disetujui':
                    ket_simpan = f"Terlambat (ACC Pembimbing): {pengajuan_terlambat['alasan']}"
                else:
                    ket_simpan = "Tepat Waktu"

                cursor.execute("""
                    INSERT INTO absensi (siswa_id, tanggal, status, keterangan, foto_bukti, lokasi, is_manual, created_at) 
                    VALUES (%s, %s, 'Hadir', %s, %s, %s, 0, NOW())
                """, (siswa_id, today_str, ket_simpan, filename_db, lokasi))
                
                conn.commit()
                flash('Presensi selfie berhasil disimpan!', 'success')
                cursor.close()
                conn.close()
                return redirect(url_for('riwayat_absensi'))
            except Exception as e:
                conn.rollback()
                flash(f'Gagal memproses presensi: {e}', 'danger')

    cursor.execute("SELECT * FROM siswa WHERE id = %s", (siswa_id,))
    siswa = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template('absensi.html',
                           today=today_str, 
                           absensi_hari_ini=absensi_hari_ini,
                           pengajuan_terlambat=pengajuan_terlambat,
                           pengajuan_izin_sakit=pengajuan_izin_sakit,
                           is_terlambat=is_terlambat,
                           presensi_tutup=presensi_tutup,
                           siswa=siswa)


@app.route('/absensi/riwayat')
def riwayat_absensi():
    if not is_logged_in():
        return redirect(url_for('login'))

    role = session.get('role')
    if role == 'pembimbing_pkl':
        return redirect(url_for('pkl.absensi'))   # modul pkl terpisah
    if role != 'siswa' and not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if role == 'siswa':
        siswa_id = session.get('siswa_id')
        cursor.execute("""
            SELECT
                a.*,
                TIME_FORMAT(a.created_at, '%H:%i') AS jam_absen
            FROM absensi a
            WHERE a.siswa_id = %s 
            ORDER BY a.tanggal DESC
        """, (siswa_id,))
        
        absensi_list = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('riwayat_absensi.html', absensi_list=absensi_list, is_pembimbing=False)

    else:
        filter_tanggal = request.args.get('tanggal', '').strip()
        filter_status = request.args.get('status', '').strip()
        filter_nama = request.args.get('nama_siswa', '').strip()

        query = """
            SELECT 
                a.*, 
                TIME_FORMAT(a.created_at, '%H:%i') AS jam_absen, 
                u.nama AS nama_siswa, 
                s.kelas_jurusan 
            FROM absensi a
            JOIN siswa s ON a.siswa_id = s.id
            JOIN users u ON s.user_id = u.id
            WHERE 1=1
        """
        params = []
        sc, scp = scope_sekolah('s')
        query += sc
        params.extend(scp)

        if filter_tanggal:
            query += " AND a.tanggal = %s"
            params.append(filter_tanggal)
        if filter_status:
            query += " AND a.status = %s"
            params.append(filter_status)
        if filter_nama:
            query += " AND u.nama LIKE %s"
            params.append(f"%{filter_nama}%")

        query += " ORDER BY a.tanggal DESC, u.nama ASC"

        cursor.execute(query, tuple(params))
        absensi_list = cursor.fetchall()

        # Opsi daftar siswa + sisa kuota toleransi untuk Modal Absen Manual
        cursor.execute("""
            SELECT s.id, u.nama, s.nisn, s.kelas_jurusan,
                   (1 - COUNT(CASE WHEN a.is_manual = 1 THEN 1 END)) AS sisa_toleransi
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN absensi a ON s.id = a.siswa_id
            WHERE 1=1""" + sc + """
            GROUP BY s.id, u.nama, s.nisn, s.kelas_jurusan
            ORDER BY u.nama ASC
        """, tuple(scp))
        siswa_list = cursor.fetchall()

        cursor.close()
        conn.close()
        return render_template('riwayat_absensi.html', 
                               absensi_list=absensi_list, 
                               is_pembimbing=True, 
                               siswa_list=siswa_list,
                               filter_tanggal=filter_tanggal,
                               filter_status=filter_status,
                               filter_nama=filter_nama)



# Route untuk menyajikan file gambar dari folder uploads/
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if not is_logged_in():
        abort(403)
    # Siswa hanya boleh melihat file miliknya; pembimbing boleh semua.
    if session.get('role') == 'siswa':
        conn = get_db_connection()
        if not conn:
            abort(503)
        cursor = conn.cursor()
        try:
            sid = session.get('siswa_id')
            cursor.execute("""
                SELECT 1 FROM absensi WHERE siswa_id = %s AND foto_bukti = %s
                UNION SELECT 1 FROM laporan_harian WHERE siswa_id = %s AND foto_bukti = %s
                UNION SELECT 1 FROM pengajuan_absensi WHERE siswa_id = %s AND bukti_file = %s
                UNION SELECT 1 FROM siswa WHERE id = %s AND foto_profil = %s
                LIMIT 1
            """, (sid, filename) * 4)
            if cursor.fetchone() is None:
                abort(403)
        finally:
            cursor.close()
            conn.close()
    elif session.get('role') == 'pembimbing_pkl':
        # Hanya file milik siswa BIMBINGANnya (siswa.pembimbing_pkl_id = user ini)
        conn = get_db_connection()
        if not conn:
            abort(503)
        cursor = conn.cursor()
        try:
            uid = session.get('user_id')
            cursor.execute("""
                SELECT 1 FROM absensi a JOIN siswa s ON a.siswa_id = s.id
                    WHERE a.foto_bukti = %s AND s.pembimbing_pkl_id = %s
                UNION SELECT 1 FROM laporan_harian l JOIN siswa s ON l.siswa_id = s.id
                    WHERE l.foto_bukti = %s AND s.pembimbing_pkl_id = %s
                UNION SELECT 1 FROM pengajuan_absensi p JOIN siswa s ON p.siswa_id = s.id
                    WHERE p.bukti_file = %s AND s.pembimbing_pkl_id = %s
                UNION SELECT 1 FROM siswa s WHERE s.foto_profil = %s AND s.pembimbing_pkl_id = %s
                LIMIT 1
            """, (filename, uid) * 4)
            if cursor.fetchone() is None:
                abort(403)
        finally:
            cursor.close()
            conn.close()

    # Admin / pembimbing industri boleh semua file. Cari di folder bukti, lalu folder foto profil.
    folder = app.config['UPLOAD_FOLDER']
    if not os.path.isfile(os.path.join(folder, filename)):
        folder = app.config['UPLOAD_FOLDER_PROFIL']
    if not os.path.isfile(os.path.join(folder, filename)):
        abort(404)
    resp = send_from_directory(folder, filename)
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


# Foto profil disajikan lewat route (bukan /static) supaya ikut folder Volume Railway.
@app.route('/foto-profil/<path:filename>')
def foto_profil_file(filename):
    if not is_logged_in():
        abort(403)
    folder = app.config['UPLOAD_FOLDER_PROFIL']
    if not os.path.isfile(os.path.join(folder, filename)):
        abort(404)
    resp = send_from_directory(folder, filename)
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp

@app.route('/laporan')
def laporan():
    if not is_logged_in() or session.get('role') != 'siswa':
        flash('Akses ditolak. Silakan login sebagai Siswa.', 'danger')
        return redirect(url_for('login'))

    siswa_id = session.get('siswa_id')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # PERBAIKAN: Gunakan created_at DESC agar aman dari error kolom tanggal
    cursor.execute("""
        SELECT * FROM laporan_harian 
        WHERE siswa_id = %s 
        ORDER BY created_at DESC
    """, (siswa_id,))
    laporan_list = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('laporan.html', laporan_list=laporan_list)

@app.route('/laporan/tambah', methods=['GET', 'POST'])
def laporan_tambah():
    if not is_logged_in() or session.get('role') != 'siswa':
        flash('Akses ditolak. Silakan login sebagai Siswa.', 'danger')
        return redirect(url_for('login'))

    libur = tolak_jika_hari_minggu('mengirim laporan harian')
    if libur:
        return libur

    siswa_id = session.get('siswa_id')
    today_str = today_wib().strftime('%Y-%m-%d')
    now = now_wib()
    is_terlambat = now.hour >= 11
    is_alpa_waktu = now.hour >= 15  # Batas waktu lewat jam 15.00 WIB

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 1. Cek status absensi hari ini di tabel absensi
    cursor.execute("""
        SELECT status FROM absensi 
        WHERE siswa_id = %s AND tanggal = %s
    """, (siswa_id, today_str))
    absensi_today = cursor.fetchone()
    status_absen = absensi_today['status'].lower() if (absensi_today and absensi_today.get('status')) else None

    # 2. Cek apakah ada data pengajuan (Izin, Sakit, atau Terlambat) hari ini
    cursor.execute("""
        SELECT status_pengajuan, jenis FROM pengajuan_absensi 
        WHERE siswa_id = %s AND tanggal = %s
        ORDER BY created_at DESC LIMIT 1
    """, (siswa_id, today_str))
    pengajuan_today = cursor.fetchone()

    cursor.close()
    conn.close()

    # ==========================================
    # 3. VALIDASI HAK AKSES ISI LAPORAN HARIAN (DIPERBAIKI)
    # ==========================================
    
    # Prioritas 1: Cek apakah siswa belum melakukan absensi sama sekali
    if not status_absen and not pengajuan_today:
        flash('Anda belum melakukan Absensi Hadir hari ini! Silakan absen terlebih dahulu sebelum mengisi laporan.', 'danger')
        return redirect(url_for('laporan'))

    # Prioritas 2: Cek apakah sudah lewat jam 15.00 (Tercatat Alpa / Terlambat batas waktu)
    if is_alpa_waktu:
        flash('Waktu pengisian laporan telah melewati pukul 15.00 WIB. Anda tercatat Alpa.', 'danger')
        return redirect(url_for('laporan'))

    # Prioritas 3: Cek jika status absensi adalah Izin atau Sakit
    if status_absen in ['izin', 'sakit']:
        flash(f'Hari ini Anda tercatat {status_absen.capitalize()}. Anda tidak perlu mengisi laporan harian.', 'warning')
        return redirect(url_for('laporan'))

    # Prioritas 4: Cek pengajuan absensi (jika ada)
    if pengajuan_today:
        status_p = pengajuan_today['status_pengajuan']
        jenis_p = pengajuan_today['jenis']

        if jenis_p in ['Izin', 'Sakit']:
            if status_p == 'Pending':
                flash(f'Pengajuan {jenis_p} Anda sedang menunggu persetujuan Pembimbing.', 'warning')
            elif status_p == 'Disetujui':
                flash(f'Pengajuan {jenis_p} Anda hari ini sudah disetujui. Anda tidak perlu mengisi laporan harian.', 'info')
            elif status_p == 'Ditolak':
                flash(f'Pengajuan {jenis_p} Anda ditolak. Silakan lakukan absensi hadir.', 'danger')
            return redirect(url_for('laporan'))

        elif jenis_p == 'Terlambat':
            if status_p == 'Pending':
                flash('Pengajuan keterlambatan Anda sedang menunggu persetujuan Pembimbing.', 'warning')
                return redirect(url_for('laporan'))
            elif status_p == 'Disetujui' and status_absen != 'hadir':
                flash('Pengajuan terlambat Anda sudah di-ACC! Silakan lakukan absensi foto terlebih dahulu.', 'warning')
                return redirect(url_for('absensi'))
            elif status_p == 'Ditolak':
                flash('Pengajuan keterlambatan Anda ditolak oleh Pembimbing.', 'danger')
                return redirect(url_for('laporan'))

    # ==========================================
    # 4. PROSES POST & RENDER FORM LAPORAN
    # ==========================================
    if request.method == 'POST':
        tanggal = request.form.get('tanggal', today_str)
        deskripsi_kegiatan = request.form.get('deskripsi_kegiatan', '').strip()
        alasan_terlambat = request.form.get('alasan_terlambat', '').strip()
        file_foto = request.files.get('foto_bukti')

        # Validasi Input Form
        if not tanggal or not deskripsi_kegiatan:
            flash('Tanggal dan Deskripsi Kegiatan wajib diisi!', 'danger')
            return render_template('laporan_form.html', is_edit=False, today=today_str, is_terlambat=is_terlambat)

        if is_terlambat and not alasan_terlambat:
            flash('Pengiriman terlambat! Harap isi alasan keterlambatan Anda.', 'danger')
            return render_template('laporan_form.html', is_edit=False, today=today_str, is_terlambat=is_terlambat)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # VALIDASI PENTING: Cek apakah laporan untuk tanggal tersebut sudah pernah dibuat sebelumnya
        cursor.execute("""
            SELECT id FROM laporan_harian 
            WHERE siswa_id = %s AND tanggal = %s
        """, (siswa_id, tanggal))
        existing_laporan = cursor.fetchone()

        if existing_laporan:
            cursor.close()
            conn.close()
            flash(f'Laporan harian untuk tanggal {tanggal} sudah pernah dibuat! Silakan pilih tanggal lain.', 'danger')
            return render_template('laporan_form.html', is_edit=False, today=today_str, is_terlambat=is_terlambat)

        # Upload Foto Bukti
        filename_db = None
        if file_foto and file_foto.filename != '':
            if not allowed_file(file_foto.filename):
                cursor.close()
                conn.close()
                flash('Format file tidak didukung! Gunakan format PNG, JPG, atau JPEG.', 'danger')
                return render_template('laporan_form.html', is_edit=False, today=today_str, is_terlambat=is_terlambat)

            original_name = secure_filename(file_foto.filename)
            unique_name = f"{uuid.uuid4().hex}_{original_name}"
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
            filename_db = unique_name

        try:
            cursor.execute("""
                INSERT INTO laporan_harian 
                (siswa_id, tanggal, deskripsi_kegiatan, foto_bukti, status_validasi, alasan_terlambat)
                VALUES (%s, %s, %s, %s, 'Pending', %s)
            """, (siswa_id, tanggal, deskripsi_kegiatan, filename_db, alasan_terlambat if is_terlambat else None))

            conn.commit()
            flash('Laporan harian berhasil dikirim!', 'success')
            return redirect(url_for('laporan'))

        except Exception as e:
            conn.rollback()
            print(f"[ERROR SAVE LAPORAN]: {e}")
            flash(f'Terjadi kesalahan saat menyimpan laporan: {str(e)}', 'danger')
            return render_template('laporan_form.html', is_edit=False, today=today_str, is_terlambat=is_terlambat)

        finally:
            cursor.close()
            conn.close()

    return render_template('laporan_form.html', is_edit=False, today=today_str, is_terlambat=is_terlambat)

@app.route('/laporan/edit/<int:laporan_id>', methods=['GET', 'POST'])
def laporan_edit(laporan_id):
    if not is_logged_in() or session.get('role') != 'siswa':
        flash('Akses ditolak. Silakan login sebagai Siswa.', 'danger')
        return redirect(url_for('login'))

    siswa_id = session.get('siswa_id')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM laporan_harian WHERE id = %s AND siswa_id = %s", (laporan_id, siswa_id))
    laporan_data = cursor.fetchone()

    if not laporan_data:
        cursor.close()
        conn.close()
        flash('Laporan tidak ditemukan!', 'danger')
        return redirect(url_for('laporan'))

    # ATURAN EDIT: Hanya boleh jika statusnya Pending atau Revisi. Jika Disetujui, tolak total!
    if laporan_data['status_validasi'] == 'Disetujui':
        cursor.close()
        conn.close()
        flash('Laporan yang sudah disetujui oleh pembimbing tidak dapat diubah kembali!', 'danger')
        return redirect(url_for('laporan'))

    if request.method == 'POST':
        tanggal = request.form.get('tanggal', laporan_data['tanggal'])
        deskripsi_kegiatan = request.form.get('deskripsi_kegiatan', '').strip()
        file_foto = request.files.get('foto_bukti')

        # Cek duplikasi tanggal jika tanggal diubah saat edit
        if tanggal != str(laporan_data['tanggal']):
            cursor.execute("""
                SELECT id FROM laporan_harian 
                WHERE siswa_id = %s AND tanggal = %s AND id != %s
            """, (siswa_id, tanggal, laporan_id))
            if cursor.fetchone():
                cursor.close()
                conn.close()
                flash(f'Laporan untuk tanggal {tanggal} sudah ada! Silakan pilih tanggal lain.', 'danger')
                return render_template('laporan_form.html', is_edit=True, laporan=laporan_data)

        filename_db = laporan_data['foto_bukti']
        if file_foto and file_foto.filename != '':
            if not allowed_file(file_foto.filename):
                cursor.close()
                conn.close()
                flash('Format file tidak didukung! Gunakan PNG, JPG, atau JPEG.', 'danger')
                return render_template('laporan_form.html', is_edit=True, laporan=laporan_data)

            original_name = secure_filename(file_foto.filename)
            unique_name = f"{uuid.uuid4().hex}_{original_name}"
            
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
            filename_db = unique_name

        try:
            # Jika status sebelumnya 'Revisi', ubah kembali menjadi 'Pending' saat diedit ulang oleh siswa
            new_status = 'Pending' if laporan_data['status_validasi'] == 'Revisi' else laporan_data['status_validasi']

            cursor.execute("""
                UPDATE laporan_harian 
                SET tanggal = %s, deskripsi_kegiatan = %s, foto_bukti = %s, status_validasi = %s
                WHERE id = %s AND siswa_id = %s
            """, (tanggal, deskripsi_kegiatan, filename_db, new_status, laporan_id, siswa_id))
            conn.commit()
            flash('Laporan harian berhasil diperbarui!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('laporan'))
        except mysql.connector.Error as e:
            conn.rollback()
            flash(f'Gagal mengupdate laporan: {e}', 'danger')

    cursor.close()
    conn.close()
    return render_template('laporan_form.html', is_edit=True, laporan=laporan_data)


@app.route('/laporan/detail/<int:laporan_id>')
def laporan_detail(laporan_id):
    if not is_logged_in():
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)


    cursor.execute("""
        SELECT
            l.*,
            u.nama AS nama_siswa,
            s.kelas_jurusan,
            sch.nama AS sekolah
        FROM laporan_harian l
        JOIN siswa s ON l.siswa_id = s.id
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah sch ON s.sekolah_id = sch.id
        WHERE l.id = %s
    """, (laporan_id,))

    laporan_data = cursor.fetchone()

    cursor.close()
    conn.close()

    if not laporan_data:
        flash('Detail laporan tidak ditemukan!', 'danger')
        return redirect(url_for('laporan'))

    # Siswa hanya boleh membuka laporannya sendiri; staf dibatasi scope sekolah.
    if session.get('role') == 'siswa':
        if laporan_data['siswa_id'] != session.get('siswa_id'):
            abort(403)
    elif not is_staff() or not akses_laporan(laporan_id):
        abort(403)

    return render_template('laporan_detail.html', laporan=laporan_data)


# ==================== MODUL VALIDASI LAPORAN (PEMBIMBING) ====================

@app.route('/laporan/pembimbing')
def validasi_laporan():
    if not is_staff():
        flash('Akses ditolak. Halaman khusus Pembimbing.', 'danger')
        return redirect(url_for('login'))

    filter_status = request.args.get('status', '').strip()
    filter_siswa = request.args.get('siswa_id', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT l.*, u.nama as nama_siswa, s.kelas_jurusan 
        FROM laporan_harian l
        JOIN siswa s ON l.siswa_id = s.id
        JOIN users u ON s.user_id = u.id
        WHERE 1=1
    """
    params = []
    sc, scp = scope_sekolah('s')
    query += sc
    params.extend(scp)

    if filter_status:
        query += " AND l.status_validasi = %s"
        params.append(filter_status)
    if filter_siswa:
        query += " AND l.siswa_id = %s"
        params.append(filter_siswa)

    # PERBAIKAN: Gunakan l.created_at DESC agar tidak error 1054
    query += " ORDER BY l.created_at DESC"

    cursor.execute(query, tuple(params))
    laporan_list = cursor.fetchall()

    # Opsi filter daftar siswa
    cursor.execute("SELECT s.id, u.nama FROM siswa s JOIN users u ON s.user_id = u.id WHERE 1=1"
                   + sc + " ORDER BY u.nama ASC", tuple(scp))
    dft_siswa = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('validasi_laporan.html', 
                           laporan_list=laporan_list, 
                           dft_siswa=dft_siswa,
                           filter_status=filter_status,
                           filter_siswa=filter_siswa)


@app.route('/laporan/pembimbing/detail/<int:laporan_id>', methods=['GET', 'POST'])
def validasi_detail(laporan_id):
    if not is_staff():
        flash('Akses ditolak. Halaman khusus Pembimbing.', 'danger')
        return redirect(url_for('login'))

    if not akses_laporan(laporan_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        action = request.form.get('action')
        catatan = request.form.get('catatan_pembimbing', '').strip()

        if action not in ['Disetujui', 'Revisi']:
            flash('Aksi validasi tidak valid!', 'danger')
        else:
            try:
                cursor.execute("""
                    UPDATE laporan_harian 
                    SET status_validasi = %s, catatan_pembimbing = %s 
                    WHERE id = %s
                """, (action, catatan, laporan_id))
                conn.commit()
                flash(f'Laporan harian berhasil diperbarui menjadi {action}!', 'success')
                return redirect(url_for('validasi_laporan'))
            except mysql.connector.Error as e:
                flash(f'Gagal memperbarui status laporan: {e}', 'danger')


    cursor.execute("""
        SELECT
            l.*,
            u.nama AS nama_siswa,
            s.kelas_jurusan,
            sch.nama AS sekolah,
            s.nisn
        FROM laporan_harian l
        JOIN siswa s ON l.siswa_id = s.id
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah sch ON s.sekolah_id = sch.id
        WHERE l.id = %s
    """, (laporan_id,))
    laporan_data = cursor.fetchone()

    cursor.close()
    conn.close()

    if not laporan_data:
        flash('Data laporan tidak ditemukan!', 'danger')
        return redirect(url_for('validasi_laporan'))

    return render_template('validasi_detail.html', laporan=laporan_data)

# ==================== MODUL PENGAJUAN IZIN / SAKIT (SISWA) ====================
# ==================== MODUL PENGAJUAN IZIN / SAKIT (SISWA) ====================
@app.route('/pengajuan-absensi', methods=['GET', 'POST'])
def pengajuan_absensi():
    if not is_logged_in() or session.get('role') != 'siswa':
        flash('Akses ditolak. Silakan login sebagai Siswa.', 'danger')
        return redirect(url_for('login'))

    libur = tolak_jika_hari_minggu('mengajukan izin/sakit/terlambat')
    if libur:
        return libur

    siswa_id = session.get('siswa_id')
    today_str = today_wib().strftime('%Y-%m-%d')
    
    # Jalankan pengecekan Auto-Alpa (jika waktu sudah > 15:00 WIB)
    cek_dan_set_alpa_otomatis(siswa_id, today_str)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # 1. Cek status absensi hari ini di tabel absensi (Hadir/Alpa/Izin/Sakit)
    cursor.execute("""
        SELECT status FROM absensi 
        WHERE siswa_id = %s AND tanggal = %s
    """, (siswa_id, today_str))
    absensi_today = cursor.fetchone()
    
    status_absen_hari_ini = absensi_today['status'] if absensi_today else None
    sudah_hadir = True if (status_absen_hari_ini and status_absen_hari_ini.lower() == 'hadir') else False
    sudah_alpa = True if (status_absen_hari_ini and status_absen_hari_ini.lower() == 'alpa') else False

    # 2. Cek apakah sudah pernah mengajukan izin/sakit/terlambat hari ini
    cursor.execute("""
        SELECT id FROM pengajuan_absensi 
        WHERE siswa_id = %s AND tanggal = %s
    """, (siswa_id, today_str))
    pengajuan_today = cursor.fetchone()
    sudah_pengajuan = True if pengajuan_today else False

    presensi_tutup = presensi_ditutup()

    if request.method == 'POST':
        # CEK 0: Setelah pukul 15:00 WIB pengajuan Izin/Sakit ditutup
        if presensi_tutup and not absensi_today:
            flash('Pengajuan Izin/Sakit telah ditutup pukul 15:00 WIB untuk hari ini.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('pengajuan_absensi'))

        # CEK A: Jika sudah Hadir
        if sudah_hadir:
            flash('Anda sudah mengisi absensi hadir hari ini, sehingga tidak dapat mengajukan izin/sakit.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('pengajuan_absensi'))

        # CEK B: Jika sudah ALPA (Waktu habis > 15:00 WIB atau Alpa Manual)
        if sudah_alpa:
            flash('Waktu presensi dan pengajuan telah ditutup. Anda telah tercatat ALPA untuk hari ini.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('pengajuan_absensi'))
        
        # CEK C: Jika sudah ada pengajuan sebelumnya
        if sudah_pengajuan:
            flash('Anda sudah mengirimkan pengajuan untuk hari ini.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('pengajuan_absensi'))

        jenis = request.form.get('jenis')
        alasan = request.form.get('alasan', '').strip()
        file_bukti = request.files.get('bukti_file')

        if jenis not in ['Izin', 'Sakit'] or not alasan:
            flash('Pilih jenis pengajuan dan isi alasan dengan benar!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('pengajuan_absensi'))

        filename_db = None
        if file_bukti and file_bukti.filename != '':
            if allowed_file(file_bukti.filename):
                original_name = secure_filename(file_bukti.filename)
                unique_name = f"{uuid.uuid4().hex}_{original_name}"
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file_bukti.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
                filename_db = unique_name

        try:
            cursor.execute("""
                INSERT INTO pengajuan_absensi (siswa_id, tanggal, jenis, alasan, bukti_file, status_pengajuan, created_at)
                VALUES (%s, %s, %s, %s, %s, 'Pending', NOW())
            """, (siswa_id, today_str, jenis, alasan, filename_db))
            conn.commit()
            flash('Pengajuan Izin/Sakit berhasil dikirim! Menunggu persetujuan Pembimbing.', 'success')
            return redirect(url_for('pengajuan_absensi'))
        except mysql.connector.Error as e:
            conn.rollback()
            flash(f'Gagal mengirim pengajuan: {e}', 'danger')

    cursor.execute("SELECT * FROM pengajuan_absensi WHERE siswa_id = %s ORDER BY created_at DESC", (siswa_id,))
    pengajuan_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'pengajuan_absensi.html', 
        pengajuan_list=pengajuan_list, 
        today=today_str,
        sudah_hadir=sudah_hadir,
        sudah_alpa=sudah_alpa, # Variabel baru dikirim ke HTML
        presensi_tutup=presensi_tutup,
        sudah_pengajuan=sudah_pengajuan
    )

# ==================== MODUL CETAK REKAPITULASI ====================

@app.route('/cetak/absensi')
def cetak_absensi():
    if not is_logged_in():
        return redirect(url_for('login'))

    role = session.get('role')
    siswa_id = request.args.get('siswa_id', type=int)

    # Jika login sebagai siswa, otomatis cetak absensi sendiri
    if role == 'siswa':
        siswa_id = session.get('siswa_id')
    elif not siswa_id:
        flash('Silakan pilih siswa yang akan dicetak!', 'warning')
        return redirect(url_for('riwayat_absensi'))
    elif not is_staff() or not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. Detail Siswa
    cursor.execute("""
        SELECT s.*, u.nama, u.username, k.nama AS nama_sekolah
        FROM siswa s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah k ON s.sekolah_id = k.id
        WHERE s.id = %s
    """, (siswa_id,))
    detail_siswa = cursor.fetchone()
    if not detail_siswa:
        cursor.close()
        conn.close()
        abort(404)

    # 2. Daftar Absensi
    cursor.execute("""
        SELECT * FROM absensi 
        WHERE siswa_id = %s 
        ORDER BY tanggal ASC
    """, (siswa_id,))
    absensi_list = cursor.fetchall()

    # 3. Rekap Total
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN status = 'Hadir' THEN 1 ELSE 0 END) as hadir,
            SUM(CASE WHEN status = 'Izin' THEN 1 ELSE 0 END) as izin,
            SUM(CASE WHEN status = 'Sakit' THEN 1 ELSE 0 END) as sakit,
            SUM(CASE WHEN status = 'Alpa' THEN 1 ELSE 0 END) as alpa
        FROM absensi WHERE siswa_id = %s
    """, (siswa_id,))
    rekap = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template('cetak_absensi.html', siswa=detail_siswa, absensi_list=absensi_list, rekap=rekap)


@app.route('/cetak/laporan')
def cetak_laporan():
    if not is_logged_in():
        return redirect(url_for('login'))

    role = session.get('role')
    siswa_id = request.args.get('siswa_id', type=int)

    if role == 'siswa':
        siswa_id = session.get('siswa_id')
    elif not siswa_id:
        flash('Silakan pilih siswa yang akan dicetak!', 'warning')
        return redirect(url_for('validasi_laporan'))
    elif not is_staff() or not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. Detail Siswa
    cursor.execute("""
        SELECT s.*, u.nama, u.username, k.nama AS nama_sekolah
        FROM siswa s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah k ON s.sekolah_id = k.id
        WHERE s.id = %s
    """, (siswa_id,))
    detail_siswa = cursor.fetchone()
    if not detail_siswa:
        cursor.close()
        conn.close()
        abort(404)

    # 2. Daftar Laporan Mingguan
    cursor.execute("""
        SELECT * FROM laporan_harian 
        WHERE siswa_id = %s 
        ORDER BY tanggal ASC
    """, (siswa_id,))
    laporan_list = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('cetak_laporan.html', siswa=detail_siswa, laporan_list=laporan_list)

# ==================== MODUL PERSETUJUAN ABSENSI (PEMBIMBING) ====================

@app.route('/pembimbing/pengajuan-absensi')
def persetujuan_absensi():
    if not is_staff():
        flash('Akses ditolak. Khusus Pembimbing.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    sc, scp = scope_sekolah('s')
    cursor.execute("""
        SELECT p.*, u.nama as nama_siswa, s.kelas_jurusan
        FROM pengajuan_absensi p
        JOIN siswa s ON p.siswa_id = s.id
        JOIN users u ON s.user_id = u.id
        WHERE 1=1""" + sc + """
        ORDER BY FIELD(p.status_pengajuan, 'Pending', 'Disetujui', 'Ditolak'), p.created_at DESC
    """, tuple(scp))
    pengajuan_list = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('persetujuan_absensi.html', pengajuan_list=pengajuan_list)


@app.route('/pembimbing/pengajuan-absensi/proses/<int:id>/<string:aksi>', methods=['POST'])
def proses_pengajuan(id, aksi):
    if not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    if not akses_pengajuan(id):
        abort(403)

    if aksi not in ['Disetujui', 'Ditolak']:
        flash('Aksi tidak valid!', 'danger')
        return redirect(url_for('persetujuan_absensi'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM pengajuan_absensi WHERE id = %s", (id,))
    p = cursor.fetchone()

    if p:
        try:
            # Update status pengajuan di tabel pengajuan_absensi
            cursor.execute("UPDATE pengajuan_absensi SET status_pengajuan = %s WHERE id = %s", (aksi, id))

            # Jika DISETUJUI dan jenisnya Izin / Sakit -> Langsung masuk tabel absensi
            # Jika jenisnya 'Terlambat' -> Hanya update status pengajuan agar kamera di sisi siswa bisa terbuka
            if aksi == 'Disetujui' and p['jenis'] in ['Izin', 'Sakit']:
                cursor.execute("DELETE FROM absensi WHERE siswa_id = %s AND tanggal = %s", (p['siswa_id'], p['tanggal']))
                
                cursor.execute("""
                    INSERT INTO absensi (siswa_id, tanggal, status, keterangan, foto_bukti)
                    VALUES (%s, %s, %s, %s, %s)
                """, (p['siswa_id'], p['tanggal'], p['jenis'], f"{p['jenis']}: {p['alasan']}", p.get('bukti_file')))

            conn.commit()
            
            if p['jenis'] == 'Terlambat' and aksi == 'Disetujui' and _ke_tanggal(p['tanggal']) == today_wib() and presensi_ditutup():
                flash("Pengajuan Terlambat di ACC, tetapi sudah lewat pukul 15:00 WIB sehingga siswa tidak bisa lagi presensi selfie hari ini. Gunakan Absen Manual bila perlu mencatat kehadirannya.", 'warning')
            elif p['jenis'] == 'Terlambat' and aksi == 'Disetujui':
                flash(f"Pengajuan Terlambat di ACC. Siswa sekarang sudah bisa melakukan absensi foto selfie.", 'success')
            else:
                flash(f"Pengajuan {p['jenis']} berhasil di {aksi}!", 'success')

        except mysql.connector.Error as e:
            conn.rollback()
            flash(f'Terjadi kesalahan database: {e}', 'danger')

    cursor.close()
    conn.close()
    return redirect(url_for('persetujuan_absensi'))

@app.route('/pembimbing/siswa/tambah', methods=['GET', 'POST'])
def tambah_siswa_page():
    if not is_staff():
        flash('Akses ditolak. Silakan login sebagai Pembimbing.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('daftar_siswa'))
    cursor = conn.cursor(dictionary=True)

    form = dict(nama='', nisn='', kelas_jurusan='', sekolah_id=None, tgl_mulai_pkl='', tgl_selesai_pkl='')
    try:
        sekolah_opsi = daftar_sekolah_boleh(cursor)
        if len(sekolah_opsi) == 1:
            form['sekolah_id'] = sekolah_opsi[0]['id']

        if request.method == 'POST':
            form['nama'] = request.form.get('nama', '').strip()
            form['nisn'] = request.form.get('nisn', '').strip()
            form['kelas_jurusan'] = request.form.get('kelas_jurusan', '').strip()
            form['tgl_mulai_pkl'] = request.form.get('tgl_mulai_pkl', '').strip() or None
            form['tgl_selesai_pkl'] = request.form.get('tgl_selesai_pkl', '').strip() or None
            
            form['sekolah_id'] = request.form.get('sekolah_id', type=int)

            # Validasi apakah sekolah_id yang dipilih valid ada di sekolah_opsi
            sekolah_valid = any(o['id'] == form['sekolah_id'] for o in sekolah_opsi)

            if not form['nama'] or not form['nisn'] or not form['kelas_jurusan'] or not sekolah_valid:
                flash('Harap isi semua bidang wajib dengan benar!', 'danger')
            else:
                cursor.execute("SELECT id FROM users WHERE username = %s", (form['nisn'],))
                if cursor.fetchone():
                    flash(f"NISN {form['nisn']} sudah terdaftar. Harap gunakan NISN lain.", 'danger')
                else:
                    try:
                        hashed_pw = generate_password_hash(form['nisn'])
                        cursor.execute("""
                            INSERT INTO users (username, password, nama, role)
                            VALUES (%s, %s, %s, 'siswa')
                        """, (form['nisn'], hashed_pw, form['nama']))
                        user_id = cursor.lastrowid

                        # PERBAIKAN: Jumlah placeholder %s disesuaikan menjadi 6 buah
                        cursor.execute("""
                            INSERT INTO siswa (user_id, nisn, kelas_jurusan, sekolah_id, tgl_mulai_pkl, tgl_selesai_pkl)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (user_id, form['nisn'], form['kelas_jurusan'], form['sekolah_id'],
                              form['tgl_mulai_pkl'], form['tgl_selesai_pkl']))
                        
                        conn.commit()
                        flash(f"{form['nama']} (NISN: {form['nisn']}) berhasil ditambahkan!", 'success')
                        return redirect(url_for('daftar_siswa'))
                    except mysql.connector.Error as e:
                        conn.rollback()
                        flash(f'Terjadi kesalahan saat menyimpan data: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return render_template('tambah_siswa.html', sekolah_opsi=sekolah_opsi, **form)

@app.route('/pembimbing/siswa/reset-password/<int:siswa_id>', methods=['POST'])
def reset_password_siswa(siswa_id):
    if not is_staff():
        flash('Akses ditolak. Khusus Pembimbing.', 'danger')
        return redirect(url_for('login'))

    if not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Ambil data NISN dan user_id siswa
        cursor.execute("""
            SELECT s.nisn, s.user_id, u.nama 
            FROM siswa s 
            JOIN users u ON s.user_id = u.id 
            WHERE s.id = %s
        """, (siswa_id,))
        siswa = cursor.fetchone()

        if not siswa:
            flash('Data siswa tidak ditemukan!', 'danger')
            return redirect(url_for('daftar_siswa'))

        # Hash password baru menggunakan NISN
        hashed_password = generate_password_hash(siswa['nisn'])

        # Update password di tabel users
        cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_password, siswa['user_id']))
        conn.commit()

        flash(f"Password untuk siswa {siswa['nama']} berhasil direset kembali ke NISN ({siswa['nisn']})!", 'success')

    except mysql.connector.Error as e:
        conn.rollback()
        flash(f'Gagal mereset password: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('detail_siswa', siswa_id=siswa_id))

# =========================================================
# ROUTE: EDIT DATA SISWA (PEMBIMBING)
# =========================================================
@app.route('/pembimbing/siswa/edit/<int:siswa_id>', methods=['GET', 'POST'])
def edit_siswa_page(siswa_id):
    if not is_staff():
        flash('Akses ditolak. Silakan login sebagai Pembimbing.', 'danger')
        return redirect(url_for('login'))

    if not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT s.*, u.nama, u.username, k.nama AS sekolah, k.nama AS nama_sekolah
        FROM siswa s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN sekolah k ON s.sekolah_id = k.id
        WHERE s.id = %s
    """, (siswa_id,))
    siswa = cursor.fetchone()
    sekolah_opsi = daftar_sekolah_boleh(cursor)

    if not siswa:
        cursor.close()
        conn.close()
        flash('Data siswa tidak ditemukan!', 'danger')
        return redirect(url_for('daftar_siswa'))

    if request.method == 'POST':
        nama = request.form.get('nama', '').strip()
        nisn = request.form.get('nisn', '').strip()
        kelas_jurusan = request.form.get('kelas_jurusan', '').strip()
        
        sekolah_id = request.form.get('sekolah_id', type=int)

        # Validasi apakah sekolah_id yang dipilih valid ada di sekolah_opsi
        sekolah_valid = any(o['id'] == sekolah_id for o in sekolah_opsi)
        
        tgl_mulai = request.form.get('tgl_mulai_pkl', '').strip() or None
        tgl_selesai = request.form.get('tgl_selesai_pkl', '').strip() or None

        if not nama or not nisn or not kelas_jurusan or not sekolah_valid:
            flash('Harap isi semua bidang wajib dengan benar!', 'danger')
            return render_template('edit_siswa.html', siswa=siswa, sekolah_opsi=sekolah_opsi)

        try:
            cursor.execute("UPDATE users SET nama = %s, username = %s WHERE id = %s", (nama, nisn, siswa['user_id']))

            # UPDATE DATA SISWA DAN PERIODE PKL
            cursor.execute("""
                UPDATE siswa 
                SET nisn = %s, kelas_jurusan = %s, sekolah_id = %s, tgl_mulai_pkl = %s, tgl_selesai_pkl = %s 
                WHERE id = %s
            """, (nisn, kelas_jurusan, sekolah_id, tgl_mulai, tgl_selesai, siswa_id))

            # Pindah sekolah -> bimbingan pembimbing PKL (terikat sekolah lama) dilepas
            cursor.execute("""
                UPDATE siswa s JOIN users g ON s.pembimbing_pkl_id = g.id
                SET s.pembimbing_pkl_id = NULL
                WHERE s.id = %s AND NOT (g.sekolah_id <=> %s)
            """, (siswa_id, sekolah_id))

            conn.commit()
            flash(f'Data siswa {nama} berhasil diperbarui!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('daftar_siswa'))

        except mysql.connector.Error as e:
            conn.rollback()
            flash(f'Terjadi kesalahan database: {e}', 'danger')

    cursor.close()
    conn.close()
    return render_template('edit_siswa.html', siswa=siswa, sekolah_opsi=sekolah_opsi)


# =========================================================
# ROUTE: TOGGLE STATUS (NONAKTIFKAN / AKTIFKAN SISWA)
# =========================================================
# =========================================================
# ROUTE: TOGGLE STATUS (NONAKTIFKAN / AKTIFKAN SISWA)
# =========================================================
@app.route('/pembimbing/siswa/toggle-status/<int:siswa_id>', methods=['POST'])
def toggle_status_siswa(siswa_id):
    if not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    if not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT s.user_id, u.nama, u.is_active 
            FROM siswa s 
            JOIN users u ON s.user_id = u.id 
            WHERE s.id = %s
        """, (siswa_id,))
        siswa = cursor.fetchone()

        if siswa:
            # Mengonversi nilai ke integer 1 atau 0 secara tegas
            current_status = int(siswa['is_active']) if siswa.get('is_active') is not None else 1
            status_baru = 0 if current_status == 1 else 1

            # Update ke database
            cursor.execute("UPDATE users SET is_active = %s WHERE id = %s", (status_baru, siswa['user_id']))
            conn.commit()

            label = "dinonaktifkan" if status_baru == 0 else "diaktifkan kembali"
            flash(f"Akun siswa {siswa['nama']} berhasil {label}!", "warning" if status_baru == 0 else "success")

    except mysql.connector.Error as e:
        conn.rollback()
        flash(f'Gagal mengubah status siswa: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(request.referrer or url_for('daftar_siswa'))

@app.route('/pembimbing/siswa/hapus/<int:siswa_id>', methods=['POST'])
def hapus_siswa(siswa_id):
    if not is_staff() or session.get('role') != 'pembimbing_industri':
        flash('Akses ditolak. Fitur ini khusus Pembimbing Industri.', 'danger')
        return redirect(url_for('login'))

    if not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('daftar_siswa'))

    cursor = conn.cursor(dictionary=True)
    try:
        # PERBAIKAN: Gunakan JOIN ke tabel users karena kolom 'nama' ada di tabel users
        cursor.execute("""
            SELECT s.user_id, u.nama 
            FROM siswa s 
            JOIN users u ON s.user_id = u.id 
            WHERE s.id = %s
        """, (siswa_id,))
        siswa = cursor.fetchone()

        if siswa:
            user_id = siswa['user_id']
            
            # 1. Hapus data terkait di tabel relasi terlebih dahulu
            cursor.execute("DELETE FROM absensi WHERE siswa_id = %s", (siswa_id,))
            cursor.execute("DELETE FROM laporan_harian WHERE siswa_id = %s", (siswa_id,))
            cursor.execute("DELETE FROM pengajuan_absensi WHERE siswa_id = %s", (siswa_id,))
            cursor.execute("DELETE FROM nilai_pkl WHERE siswa_id = %s", (siswa_id,))
            
            # 2. Hapus data dari tabel siswa
            cursor.execute("DELETE FROM siswa WHERE id = %s", (siswa_id,))
            
            # 3. Hapus data akun dari tabel users
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            
            conn.commit()
            flash(f'Akun dan seluruh data siswa {siswa["nama"]} berhasil dihapus permanen dari sistem.', 'success')
        else:
            flash('Data siswa tidak ditemukan.', 'warning')
    except mysql.connector.Error as e:
        conn.rollback()
        flash(f'Terjadi kesalahan saat menghapus data: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('daftar_siswa'))

# =========================================================
# ROUTE: INPUT & EDIT NILAI PKL SISWA
# =========================================================
@app.route('/pembimbing/siswa/nilai/<int:siswa_id>', methods=['GET', 'POST'])
def nilai_siswa_page(siswa_id):
    if not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    if not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Ambil Data Profil Siswa
        cursor.execute("""
            SELECT s.*, u.nama, u.username, k.nama AS sekolah, k.nama AS nama_sekolah
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN sekolah k ON s.sekolah_id = k.id
            WHERE s.id = %s
        """, (siswa_id,))
        siswa = cursor.fetchone()

        if not siswa:
            flash('Data siswa tidak ditemukan!', 'danger')
            return redirect(url_for('daftar_siswa'))

        # 2. Hitung Nilai Absensi Otomatis (Rasio Hadir vs Total Hari Absensi)
        cursor.execute("SELECT COUNT(*) AS total_hadir FROM absensi WHERE siswa_id = %s AND status = 'Hadir'", (siswa_id,))
        total_hadir = cursor.fetchone()['total_hadir'] or 0

        cursor.execute("SELECT COUNT(*) AS total_hari FROM absensi WHERE siswa_id = %s", (siswa_id,))
        total_hari_absen = cursor.fetchone()['total_hari'] or 1
        
        nilai_absensi_auto = min(100.0, round((total_hadir / total_hari_absen) * 100, 2))

        # 3. Hitung Nilai Laporan Otomatis dari tabel `laporan_harian` & kolom `status_validasi`
        cursor.execute("""
            SELECT COUNT(*) AS laporan_acc 
            FROM laporan_harian 
            WHERE siswa_id = %s AND status_validasi = 'Disetujui'
        """, (siswa_id,))
        laporan_acc = cursor.fetchone()['laporan_acc'] or 0
        
        nilai_laporan_auto = min(100.0, round((laporan_acc / total_hari_absen) * 100, 2))

        # 4. Ambil Nilai Eksisting (jika ada)
        cursor.execute("SELECT * FROM nilai_pkl WHERE siswa_id = %s", (siswa_id,))
        nilai = cursor.fetchone()

        if request.method == 'POST':
            try:
                nilai_sikap = max(0, min(100, int(request.form.get('nilai_sikap', 0))))
                nilai_teknis = max(0, min(100, int(request.form.get('nilai_teknis', 0))))
            except (TypeError, ValueError):
                flash('Nilai sikap dan teknis harus berupa angka 0-100!', 'danger')
                return redirect(url_for('nilai_siswa_page', siswa_id=siswa_id))
            catatan = request.form.get('catatan_pembimbing', '').strip()

            # KALKULASI NILAI AKHIR (Absensi 20% + Laporan 20% + Sikap 30% + Teknis 30%)
            nilai_akhir = round(
                (nilai_absensi_auto * 0.20) + 
                (nilai_laporan_auto * 0.20) + 
                (nilai_sikap * 0.30) + 
                (nilai_teknis * 0.30), 2
            )

            # Penentuan Predikat
            if nilai_akhir >= 85:
                predikat = 'A'
            elif nilai_akhir >= 75:
                predikat = 'B'
            elif nilai_akhir >= 65:
                predikat = 'C'
            else:
                predikat = 'D'

            if nilai:
                cursor.execute("""
                    UPDATE nilai_pkl SET 
                        nilai_absensi=%s, nilai_laporan=%s, nilai_sikap=%s, nilai_teknis=%s, 
                        nilai_akhir=%s, predikat=%s, catatan_pembimbing=%s, pembimbing_id=%s
                    WHERE siswa_id=%s
                """, (nilai_absensi_auto, nilai_laporan_auto, nilai_sikap, nilai_teknis, nilai_akhir, predikat, catatan, session['user_id'], siswa_id))
            else:
                cursor.execute("""
                    INSERT INTO nilai_pkl 
                    (siswa_id, pembimbing_id, nilai_absensi, nilai_laporan, nilai_sikap, nilai_teknis, nilai_akhir, predikat, catatan_pembimbing)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (siswa_id, session['user_id'], nilai_absensi_auto, nilai_laporan_auto, nilai_sikap, nilai_teknis, nilai_akhir, predikat, catatan))

            conn.commit()
            flash(f'Penilaian untuk {siswa["nama"]} berhasil disimpan! (Nilai Akhir: {nilai_akhir} / Predikat: {predikat})', 'success')
            return redirect(url_for('detail_siswa', siswa_id=siswa_id))

    except mysql.connector.Error as e:
        conn.rollback()
        flash(f'Terjadi kesalahan database: {e}', 'danger')
        return redirect(url_for('daftar_siswa'))
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'nilai_siswa.html', 
        siswa=siswa, 
        nilai=nilai, 
        nilai_absensi_auto=nilai_absensi_auto, 
        nilai_laporan_auto=nilai_laporan_auto
    )

# Tempat PKL yang tercetak di PDF nilai (bisa diganti lewat env NAMA_PERUSAHAAN)
NAMA_PERUSAHAAN = os.environ.get('NAMA_PERUSAHAAN', 'PT Media Naraya Cipta')


@app.route('/nilai/<int:siswa_id>/pdf')
def nilai_pkl_pdf(siswa_id):
    """Unduh PDF Nilai Akhir PKL: identitas, rekap kehadiran, rincian nilai, nilai akhir & predikat.

    Boleh diakses staf (sesuai scope sekolah) dan siswa yang bersangkutan.
    """
    if not is_logged_in():
        return redirect(url_for('login'))
    if session.get('role') == 'siswa':
        if session.get('siswa_id') != siswa_id:
            abort(403)
    elif not is_staff() or not akses_siswa(siswa_id):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT s.*, u.nama, k.nama AS nama_sekolah
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN sekolah k ON s.sekolah_id = k.id
            WHERE s.id = %s
        """, (siswa_id,))
        siswa = cursor.fetchone()
        if not siswa:
            abort(404)
        cursor.execute("""
            SELECT n.*, pb.nama AS nama_penilai
            FROM nilai_pkl n LEFT JOIN users pb ON n.pembimbing_id = pb.id
            WHERE n.siswa_id = %s
        """, (siswa_id,))
        nilai = cursor.fetchone()
        cursor.execute("""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(status = 'Hadir'), 0) AS hadir,
                   COALESCE(SUM(status = 'Izin'), 0) AS izin,
                   COALESCE(SUM(status = 'Sakit'), 0) AS sakit,
                   COALESCE(SUM(status = 'Alpa'), 0) AS alpa
            FROM absensi WHERE siswa_id = %s
        """, (siswa_id,))
        rekap = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not nilai:
        flash('Siswa ini belum dinilai, sehingga PDF nilai belum tersedia.', 'warning')
        return redirect(request.referrer or url_for('index'))

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def f(v):
        try:
            v = float(v)
            return str(int(v)) if v == int(v) else f"{v:.2f}"
        except (TypeError, ValueError):
            return '-'

    ss = getSampleStyleSheet()
    judul = ParagraphStyle('judul', parent=ss['Title'], fontSize=16, leading=20, spaceAfter=2)
    sub = ParagraphStyle('sub', parent=ss['Normal'], fontSize=10, alignment=1, textColor=colors.HexColor('#555555'))
    h2 = ParagraphStyle('h2', parent=ss['Heading3'], fontSize=11, spaceBefore=14, spaceAfter=6)
    normal = ParagraphStyle('n', parent=ss['Normal'], fontSize=10, leading=14)
    BIRU = colors.HexColor('#1e3a8a')
    ABU = colors.HexColor('#e5e7eb')

    def tabel(data, widths, header=True, align_right_cols=()):
        t = Table(data, colWidths=widths)
        gaya = [('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#9ca3af')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]
        if header:
            gaya += [('BACKGROUND', (0, 0), (-1, 0), BIRU), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                     ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
        for c in align_right_cols:
            gaya.append(('ALIGN', (c, 0), (c, -1), 'CENTER'))
        t.setStyle(TableStyle(gaya))
        return t

    mulai, selesai = siswa.get('tgl_mulai_pkl'), siswa.get('tgl_selesai_pkl')
    periode = f"{tgl_indo(mulai)} s.d. {tgl_indo(selesai)}" if mulai and selesai else '-'

    el = [Paragraph('LAPORAN NILAI AKHIR PKL', judul),
          Paragraph(f'Praktik Kerja Lapangan (PKL) di {NAMA_PERUSAHAAN}', sub), Spacer(1, 14)]

    ident = [['Nama', ':', siswa['nama']], ['NISN', ':', siswa.get('nisn') or '-'],
             ['Kelas / Jurusan', ':', siswa.get('kelas_jurusan') or '-'],
             ['Asal Sekolah', ':', siswa.get('nama_sekolah') or '-'],
             ['Tempat PKL', ':', NAMA_PERUSAHAAN], ['Periode PKL', ':', periode]]
    t = Table([[a, b, Paragraph(str(c), normal)] for a, b, c in ident], colWidths=[3.6*cm, 0.5*cm, 12.9*cm])
    t.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 10), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('TOPPADDING', (0, 0), (-1, -1), 3)]))
    el.append(t)

    el.append(Paragraph('Rekap Kehadiran', h2))
    pct = (rekap['hadir'] / rekap['total'] * 100) if rekap['total'] else 0
    el.append(tabel([['Hadir', 'Izin', 'Sakit', 'Alpa', 'Total Hari', 'Persentase Hadir'],
                     [f(rekap['hadir']), f(rekap['izin']), f(rekap['sakit']), f(rekap['alpa']),
                      f(rekap['total']), f"{pct:.1f}%"]],
                    [2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.8*cm, 4.2*cm], align_right_cols=range(6)))

    el.append(Paragraph('Rincian Nilai', h2))
    rows = [['No', 'Komponen Penilaian', 'Bobot', 'Nilai'],
            ['1', 'Kehadiran (otomatis)', '20%', f(nilai['nilai_absensi'])],
            ['2', 'Laporan Harian (otomatis)', '20%', f(nilai['nilai_laporan'])],
            ['3', 'Sikap & Kedisiplinan', '30%', f(nilai['nilai_sikap'])],
            ['4', 'Kemampuan Teknis', '30%', f(nilai['nilai_teknis'])],
            ['', 'NILAI AKHIR', '100%', f(nilai['nilai_akhir'])]]
    t = tabel(rows, [1.2*cm, 9.3*cm, 3*cm, 3.5*cm], align_right_cols=(0, 2, 3))
    t.setStyle(TableStyle([('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('BACKGROUND', (0, -1), (-1, -1), ABU)]))
    el.append(t)

    el.append(Spacer(1, 12))
    pred = Table([['PREDIKAT', nilai['predikat']]], colWidths=[5*cm, 3*cm], rowHeights=[1.4*cm])
    pred.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (0, 0), 11),
                              ('FONTSIZE', (1, 0), (1, 0), 20), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                              ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BOX', (0, 0), (-1, -1), 1, BIRU),
                              ('BACKGROUND', (0, 0), (0, 0), ABU), ('TOPPADDING', (0, 0), (-1, -1), 8),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    pred.hAlign = 'CENTER'
    el.append(pred)
    el.append(Paragraph('Keterangan predikat: A (85-100) Sangat Baik, B (75-84) Baik, C (65-74) Cukup, D (&lt;65) Kurang.',
                        ParagraphStyle('ket', parent=normal, fontSize=8, textColor=colors.HexColor('#555555'), spaceBefore=6)))

    catatan = (nilai.get('catatan_pembimbing') or '').strip()
    if catatan:
        el.append(Paragraph('Catatan Pembimbing', h2))
        from xml.sax.saxutils import escape
        el.append(Paragraph(escape(catatan).replace('\n', '<br/>'), normal))

    sekarang = now_wib()
    ttd = Table([[f"Dicetak: {tgl_indo(sekarang.date())}"],
                 ['Pembimbing Industri'], [NAMA_PERUSAHAAN], [''], [''],
                 [nilai.get('nama_penilai') or '(................................)']],
                colWidths=[7*cm])
    ttd.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 10), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                             ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold')]))
    wrap = Table([['', ttd]], colWidths=[10*cm, 7*cm])
    el.extend([Spacer(1, 28), wrap])

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm,
                      title=f"Nilai Akhir PKL - {siswa['nama']}").build(el)
    buf.seek(0)
    nama_file = re.sub(r'[^A-Za-z0-9_-]+', '_', siswa['nama']).strip('_') or 'siswa'
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f"Nilai_PKL_{nama_file}.pdf")


@app.route('/pembimbing/profil', methods=['GET'])
def profil_pembimbing():
    if not is_staff():
        flash('Akses ditolak. Silakan login terlebih dahulu.', 'danger')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('dashboard_pembimbing'))

    cursor = conn.cursor(dictionary=True)
    try:
        query = """
            SELECT u.id AS user_id, u.username, u.nama, u.role,
                   p.nama_perusahaan, p.jabatan, p.divisi, p.no_hp, p.email, p.alamat_perusahaan
            FROM users u
            LEFT JOIN pembimbing p ON u.id = p.user_id
            WHERE u.id = %s
        """
        cursor.execute(query, (user_id,))
        pembimbing_data = cursor.fetchone()

    except mysql.connector.Error as e:
        flash(f'Terjadi kesalahan database: {e}', 'danger')
        pembimbing_data = None
    finally:
        cursor.close()
        conn.close()

    return render_template('profil_pembimbing.html', pembimbing=pembimbing_data)


@app.route('/pembimbing/profil/update', methods=['POST'])
def update_profil_pembimbing():
    if not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    nama = request.form.get('nama', '').strip()
    nama_perusahaan = request.form.get('nama_perusahaan', '').strip()
    jabatan = request.form.get('jabatan', '').strip()
    divisi = request.form.get('divisi', '').strip()
    no_hp = request.form.get('no_hp', '').strip()
    email = request.form.get('email', '').strip()
    alamat_perusahaan = request.form.get('alamat_perusahaan', '').strip()

    if not nama:
        flash('Nama lengkap wajib diisi!', 'danger')
        return redirect(url_for('profil_pembimbing'))

    # Admin tidak punya data perusahaan: hanya nama yang disimpan.
    if session.get('role') == 'admin':
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET nama = %s WHERE id = %s", (nama, user_id))
            conn.commit()
            session['nama'] = nama
            flash('Profil Administrator berhasil diperbarui!', 'success')
        except mysql.connector.Error as e:
            conn.rollback()
            flash(f'Gagal memperbarui profil: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for('profil_pembimbing'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Update nama di tabel users & perbarui session nama
        cursor.execute("UPDATE users SET nama = %s WHERE id = %s", (nama, user_id))
        
        nama_bersih = nama.replace(' (Guru)', '').replace('(Guru)', '').replace(' (Pembimbing)', '').replace('(Pembimbing)', '').strip()
        session['nama'] = nama_bersih

        # 2. Simpan atau perbarui data di tabel pembimbing
        cursor.execute("SELECT id FROM pembimbing WHERE user_id = %s", (user_id,))
        pembimbing_rec = cursor.fetchone()

        if pembimbing_rec:
            cursor.execute("""
                UPDATE pembimbing 
                SET nama_perusahaan = %s, jabatan = %s, divisi = %s, no_hp = %s, email = %s, alamat_perusahaan = %s
                WHERE user_id = %s
            """, (nama_perusahaan, jabatan, divisi, no_hp, email, alamat_perusahaan, user_id))
        else:
            cursor.execute("""
                INSERT INTO pembimbing (user_id, nama_perusahaan, jabatan, divisi, no_hp, email, alamat_perusahaan)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, nama_perusahaan, jabatan, divisi, no_hp, email, alamat_perusahaan))

        conn.commit()
        flash('Profil Pembimbing Industri berhasil diperbarui!', 'success')

    except mysql.connector.Error as e:
        conn.rollback()
        flash(f'Gagal memperbarui profil: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('profil_pembimbing'))

@app.route('/pembimbing/absen-manual', methods=['POST'])
def absen_manual_pembimbing():
    if not is_staff():
        flash('Akses tidak diizinkan.', 'danger')
        return redirect(url_for('login'))

    siswa_id_form = request.form.get('siswa_id', type=int)
    if not siswa_id_form or not akses_siswa(siswa_id_form):
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    siswa_id = siswa_id_form
    tanggal = (request.form.get('tanggal') or '').strip()
    status = request.form.get('status', 'Hadir')
    keterangan = (request.form.get('keterangan') or '').strip() or 'Absen Manual oleh Pembimbing'

    try:
        datetime.strptime(tanggal, '%Y-%m-%d')
    except ValueError:
        cursor.close()
        conn.close()
        flash('Tanggal absen manual tidak valid!', 'danger')
        return redirect(url_for('riwayat_absensi'))
    if status not in ('Hadir', 'Izin', 'Sakit', 'Alpa'):
        cursor.close()
        conn.close()
        flash('Status absen manual tidak valid!', 'danger')
        return redirect(url_for('riwayat_absensi'))

    # 1. Cek batas toleransi absen manual (Maksimal 1x per siswa)
    cursor.execute("""
        SELECT COUNT(*) AS total_manual 
        FROM absensi 
        WHERE siswa_id = %s AND is_manual = 1
    """, (siswa_id,))
    cek_manual = cursor.fetchone()

    if cek_manual and cek_manual['total_manual'] >= 1:
        cursor.close()
        conn.close()
        flash('Batas toleransi absen manual untuk siswa ini sudah habis (Maksimal 1x)!', 'danger')
        return redirect(url_for('riwayat_absensi'))

    # 2. Cek apakah siswa sudah punya catatan absensi di tanggal tersebut
    cursor.execute("SELECT id FROM absensi WHERE siswa_id = %s AND tanggal = %s", (siswa_id, tanggal))
    ada_absen = cursor.fetchone()

    if ada_absen:
        cursor.close()
        conn.close()
        flash('Siswa sudah memiliki catatan presensi pada tanggal tersebut!', 'danger')
        return redirect(url_for('riwayat_absensi'))

    # 3. Simpan Absen Manual
    cursor.execute("""
        INSERT INTO absensi (siswa_id, tanggal, status, keterangan, is_manual, created_at)
        VALUES (%s, %s, %s, %s, 1, NOW())
    """, (siswa_id, tanggal, status, keterangan))
    
    conn.commit()
    cursor.close()
    conn.close()

    flash('Presensi manual berhasil disimpan!', 'success')
    return redirect(url_for('riwayat_absensi'))

@app.route('/tandai-dilihat/<int:id>', methods=['POST'])
def tandai_dilihat(id):
    if not is_staff() or not akses_pengajuan(id):
        return jsonify({'status': 'unauthorized'}), 403
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE pengajuan_absensi SET sudah_dilihat = 1 WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/pembimbing/ekspor-absensi')
def ekspor_absensi():
    if not is_staff():
        flash('Akses ditolak.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('riwayat_absensi'))
    cursor = conn.cursor(dictionary=True, buffered=True)

    # Rekap absensi seluruh siswa (Hadir / Izin / Sakit / Alpa)
    sc, scp = scope_sekolah('s')
    try:
        cursor.execute("""
            SELECT
                u.nama AS nama,
                s.nisn AS nis,
                s.kelas_jurusan,
                k.nama AS nama_sekolah,
                COALESCE(SUM(a.status = 'Hadir'), 0) AS total_hadir,
                COALESCE(SUM(a.status = 'Izin'), 0)  AS total_izin,
                COALESCE(SUM(a.status = 'Sakit'), 0) AS total_sakit,
                COALESCE(SUM(a.status = 'Alpa'), 0)  AS total_alpa
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN sekolah k ON s.sekolah_id = k.id
            LEFT JOIN absensi a ON s.id = a.siswa_id
            WHERE 1=1""" + sc + """
            GROUP BY s.id, u.nama, s.nisn, s.kelas_jurusan, k.nama
            ORDER BY u.nama ASC
        """, tuple(scp))
        rekap_data = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rekap Absensi PKL"
    ws.sheet_view.showGridLines = False

    # Font umum (tersedia di Excel/LibreOffice di semua komputer)
    FONT = 'Calibri'

    def fnt(**kw):
        return Font(name=FONT, size=kw.pop('size', 11), **kw)

    def fill(hex_):
        return PatternFill(start_color=hex_, end_color=hex_, fill_type='solid')

    def sisi(color):
        return Side(style='thin', color=color)

    thin = Border(left=sisi('CBD5E1'), right=sisi('CBD5E1'), top=sisi('CBD5E1'), bottom=sisi('CBD5E1'))
    total_border = Border(left=sisi('94A3B8'), right=sisi('94A3B8'), top=sisi('94A3B8'),
                          bottom=Side(style='double', color='0F172A'))

    # Warna per status: (latar, teks)
    warna = {
        'hadir': ('DCFCE7', '15803D'),
        'izin':  ('FEF3C7', 'B45309'),
        'sakit': ('DBEAFE', '1D4ED8'),
        'alpa':  ('FEE2E2', 'B91C1C'),
    }

    headers = ['No', 'NISN', 'Nama Siswa', 'Kelas / Jurusan', 'Sekolah', 'Hadir', 'Izin', 'Sakit', 'Alpa']
    n_kol = len(headers)
    kol_akhir = get_column_letter(n_kol)

    # Judul
    ws.merge_cells(f'A1:{kol_akhir}1')
    ws['A1'] = 'REKAPITULASI PRESENSI SISWA PKL'
    ws['A1'].font = fnt(size=15, bold=True, color='0F172A')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 30

    ws.merge_cells(f'A2:{kol_akhir}2')
    ws['A2'] = f"Sistem Informasi E-Jurnal PKL — Tanggal Cetak: {tgl_indo(today_wib())}"
    ws['A2'].font = fnt(size=10, italic=True, color='64748B')
    ws['A2'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 8

    # Header tabel (baris 4)
    ws.row_dimensions[4].height = 26
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=c, value=h)
        cell.fill = fill('4F46E5')
        cell.font = fnt(bold=True, color='FFFFFF')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = thin

    def set_teks(cell, nilai):
        """Tulis sebagai TEKS murni (mencegah nama/NISN berawalan = + - @ dibaca sebagai rumus)."""
        cell.value = nilai
        cell.data_type = 's'

    start_row = 5
    total = {'hadir': 0, 'izin': 0, 'sakit': 0, 'alpa': 0}
    for idx, row in enumerate(rekap_data, 1):
        r = start_row + idx - 1
        ws.row_dimensions[r].height = 22
        bg = fill('F8FAFC') if idx % 2 == 0 else fill('FFFFFF')

        teks = [
            (1, idx, 'center'),
            (2, str(row['nis'] or '-'), 'center'),
            (3, row['nama'] or '-', 'left'),
            (4, row['kelas_jurusan'] or '-', 'center'),
            (5, row['nama_sekolah'] or '-', 'left'),
        ]
        for col, val, al in teks:
            cell = ws.cell(row=r, column=col)
            if isinstance(val, str):
                set_teks(cell, val)
            else:
                cell.value = val
            cell.alignment = Alignment(horizontal=al, vertical='center')
            cell.font = fnt(color='0F172A')
            cell.fill = bg
            cell.border = thin

        for col, kunci in ((6, 'hadir'), (7, 'izin'), (8, 'sakit'), (9, 'alpa')):
            nilai = int(row[f'total_{kunci}'] or 0)
            total[kunci] += nilai
            cell = ws.cell(row=r, column=col, value=nilai)
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = thin
            if nilai > 0:
                cell.fill = fill(warna[kunci][0])
                cell.font = fnt(bold=True, color=warna[kunci][1])
            else:
                cell.fill = bg
                cell.font = fnt(color='94A3B8')

    # Baris total: nilai dihitung di Python (bukan rumus) supaya langsung tampil
    # juga di pratinjau HP / Google Drive / pembaca yang tidak menghitung ulang.
    total_row = start_row + len(rekap_data)
    ws.row_dimensions[total_row].height = 24
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=5)
    lbl = ws.cell(row=total_row, column=1, value='TOTAL KESELURUHAN')
    lbl.font = fnt(bold=True, color='0F172A')
    lbl.alignment = Alignment(horizontal='right', vertical='center')
    for col in range(1, 6):
        ws.cell(row=total_row, column=col).border = total_border
    for col, kunci in ((6, 'hadir'), (7, 'izin'), (8, 'sakit'), (9, 'alpa')):
        cell = ws.cell(row=total_row, column=col, value=total[kunci])
        cell.font = fnt(bold=True, color='0F172A')
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = total_border

    # Lebar kolom: dihitung dari data (judul & baris total digabung -> diabaikan)
    lebar_min = {1: 6, 2: 16, 3: 28, 4: 18, 5: 28, 6: 10, 7: 10, 8: 10, 9: 10}
    for col in range(1, n_kol + 1):
        terpanjang = len(headers[col - 1])
        for r in range(start_row, start_row + len(rekap_data)):
            v = ws.cell(row=r, column=col).value
            if v is not None:
                terpanjang = max(terpanjang, len(str(v)))
        ws.column_dimensions[get_column_letter(col)].width = min(max(terpanjang + 4, lebar_min[col]), 50)

    # Kenyamanan: header terkunci, filter, siap cetak A4 landscape
    ws.freeze_panes = 'A5'
    if rekap_data:
        ws.auto_filter.ref = f"A4:{kol_akhir}{start_row + len(rekap_data) - 1}"
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = '4:4'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"Rekap_Absensi_PKL_{today_wib().strftime('%Y%m%d')}.xlsx",
    )

# =========================================================
# MODUL ADMIN: dashboard global, kelola sekolah, kelola pembimbing
# =========================================================
@app.route('/admin')
@admin_required
def dashboard_admin():
    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('login'))
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM sekolah) AS total_sekolah,
                (SELECT COUNT(*) FROM siswa) AS total_siswa,
                (SELECT COUNT(*) FROM users WHERE role IN ('pembimbing_pkl', 'pembimbing_industri')) AS total_pembimbing,
                (SELECT COUNT(*) FROM laporan_harian WHERE status_validasi = 'Pending') AS laporan_pending,
                (SELECT COUNT(*) FROM pengajuan_absensi WHERE status_pengajuan = 'Pending') AS izin_pending,
                (SELECT COUNT(*) FROM siswa WHERE sekolah_id IS NULL) AS siswa_tanpa_sekolah,
                (SELECT COUNT(*) FROM users WHERE role = 'pembimbing_pkl' AND sekolah_id IS NULL) AS pembimbing_tanpa_sekolah
        """)
        ringkasan = cursor.fetchone()

        cursor.execute("""
            SELECT k.id, k.nama,
                (SELECT COUNT(*) FROM siswa s WHERE s.sekolah_id = k.id) AS jml_siswa,
                (SELECT COUNT(*) FROM users u WHERE u.sekolah_id = k.id AND u.role = 'pembimbing_pkl') AS jml_pembimbing,
                (SELECT COUNT(*) FROM laporan_harian l JOIN siswa s ON l.siswa_id = s.id
                    WHERE s.sekolah_id = k.id AND l.status_validasi = 'Pending') AS laporan_pending,
                (SELECT COUNT(*) FROM pengajuan_absensi p JOIN siswa s ON p.siswa_id = s.id
                    WHERE s.sekolah_id = k.id AND p.status_pengajuan = 'Pending') AS izin_pending,
                (SELECT COUNT(*) FROM absensi a JOIN siswa s ON a.siswa_id = s.id
                    WHERE s.sekolah_id = k.id AND a.status = 'Alpa') AS total_alpa
            FROM sekolah k
            ORDER BY k.nama
        """)
        per_sekolah = cursor.fetchall()
    except mysql.connector.Error as e:
        flash(f'Gagal memuat data: {e}', 'danger')
        ringkasan, per_sekolah = {}, []
    finally:
        cursor.close()
        conn.close()
    return render_template('admin_dashboard.html', ringkasan=ringkasan, per_sekolah=per_sekolah)


@app.route('/admin/sekolah', methods=['GET', 'POST'])
@admin_required
def admin_sekolah():
    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('dashboard_admin'))
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == 'POST':
            aksi = request.form.get('aksi', '')
            sekolah_id = request.form.get('sekolah_id', type=int)
            nama = request.form.get('nama', '').strip()
            npsn = request.form.get('npsn', '').strip() or None
            alamat = request.form.get('alamat', '').strip() or None
            try:
                if aksi in ('tambah', 'ubah') and not nama:
                    flash('Nama sekolah wajib diisi!', 'danger')
                elif aksi == 'tambah':
                    cursor.execute("SELECT id FROM sekolah WHERE LOWER(nama) = LOWER(%s)", (nama,))
                    if cursor.fetchone():
                        flash('Sekolah dengan nama tersebut sudah ada.', 'danger')
                    else:
                        cursor.execute("INSERT INTO sekolah (nama, npsn, alamat) VALUES (%s, %s, %s)", (nama, npsn, alamat))
                        conn.commit()
                        flash(f'Sekolah "{nama}" berhasil ditambahkan.', 'success')
                elif aksi == 'ubah' and sekolah_id:
                    cursor.execute("SELECT id FROM sekolah WHERE LOWER(nama) = LOWER(%s) AND id <> %s", (nama, sekolah_id))
                    if cursor.fetchone():
                        flash('Sekolah dengan nama tersebut sudah ada.', 'danger')
                    else:
                        cursor.execute("UPDATE sekolah SET nama = %s, npsn = %s, alamat = %s WHERE id = %s",
                                       (nama, npsn, alamat, sekolah_id))
                        conn.commit()
                        flash('Data sekolah berhasil diperbarui.', 'success')
                elif aksi == 'hapus' and sekolah_id:
                    cursor.execute("""
                        SELECT (SELECT COUNT(*) FROM siswa WHERE sekolah_id = %s) AS siswa,
                               (SELECT COUNT(*) FROM users WHERE sekolah_id = %s) AS staf
                    """, (sekolah_id, sekolah_id))
                    pakai = cursor.fetchone()
                    if pakai['siswa'] or pakai['staf']:
                        flash('Sekolah tidak bisa dihapus: masih ada siswa atau pembimbing yang terkait.', 'danger')
                    else:
                        cursor.execute("DELETE FROM sekolah WHERE id = %s", (sekolah_id,))
                        conn.commit()
                        flash('Sekolah berhasil dihapus.', 'success')
                else:
                    flash('Aksi tidak valid.', 'danger')
            except mysql.connector.Error as e:
                conn.rollback()
                flash(f'Terjadi kesalahan database: {e}', 'danger')
            return redirect(url_for('admin_sekolah'))

        cursor.execute("""
            SELECT k.*,
                (SELECT COUNT(*) FROM siswa s WHERE s.sekolah_id = k.id) AS jml_siswa,
                (SELECT COUNT(*) FROM users u WHERE u.sekolah_id = k.id) AS jml_staf
            FROM sekolah k ORDER BY k.nama
        """)
        sekolah_list = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return render_template('admin_sekolah.html', sekolah_list=sekolah_list)


@app.route('/admin/libur', methods=['GET', 'POST'])
@admin_required
def admin_libur():
    """Kelola hari libur (tanggal merah / libur perusahaan): tidak dihitung Alpa."""
    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('dashboard_admin'))
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == 'POST':
            aksi = request.form.get('aksi', '')
            try:
                if aksi == 'tambah':
                    ket = request.form.get('keterangan', '').strip()[:150]
                    sekolah_id = request.form.get('sekolah_id', type=int) or None
                    try:
                        mulai = datetime.strptime(request.form.get('tgl_mulai', ''), '%Y-%m-%d').date()
                        akhir_txt = request.form.get('tgl_akhir', '').strip()
                        akhir = datetime.strptime(akhir_txt, '%Y-%m-%d').date() if akhir_txt else mulai
                    except ValueError:
                        mulai = akhir = None
                    if not ket or not mulai:
                        flash('Tanggal dan keterangan wajib diisi!', 'danger')
                    elif akhir < mulai or (akhir - mulai).days > 60:
                        flash('Rentang tanggal tidak valid (maksimal 61 hari).', 'danger')
                    else:
                        ditambah = dihapus_alpa = 0
                        d = mulai
                        while d <= akhir:
                            cursor.execute(
                                "SELECT 1 FROM hari_libur WHERE tanggal = %s AND sekolah_id <=> %s",
                                (d.isoformat(), sekolah_id))
                            if cursor.fetchone() is None:
                                cursor.execute(
                                    "INSERT INTO hari_libur (tanggal, keterangan, sekolah_id) VALUES (%s, %s, %s)",
                                    (d.isoformat(), ket, sekolah_id))
                                ditambah += 1
                            # Hapus Alpa OTOMATIS yang sudah terlanjur tercatat pada hari libur ini
                            cursor.execute("""
                                DELETE a FROM absensi a JOIN siswa s ON a.siswa_id = s.id
                                WHERE a.tanggal = %s AND a.status = 'Alpa' AND a.is_manual = 0
                                  AND a.keterangan LIKE 'Otomatis Alpa oleh Sistem%%'
                                  AND (%s IS NULL OR s.sekolah_id = %s)
                            """, (d.isoformat(), sekolah_id, sekolah_id))
                            dihapus_alpa += max(cursor.rowcount, 0)
                            d += timedelta(days=1)
                        conn.commit()
                        flash(f'{ditambah} hari libur ditambahkan. {dihapus_alpa} Alpa otomatis pada tanggal tersebut dibersihkan.', 'success')
                elif aksi == 'hapus':
                    libur_id = request.form.get('libur_id', type=int)
                    cursor.execute("DELETE FROM hari_libur WHERE id = %s", (libur_id,))
                    conn.commit()
                    flash('Hari libur dihapus. Hari itu kembali dihitung sebagai hari PKL biasa.', 'success')
                else:
                    flash('Aksi tidak valid.', 'danger')
            except mysql.connector.Error as e:
                conn.rollback()
                flash(f'Terjadi kesalahan database: {e}', 'danger')
            return redirect(url_for('admin_libur'))

        cursor.execute("""
            SELECT h.*, k.nama AS nama_sekolah
            FROM hari_libur h LEFT JOIN sekolah k ON h.sekolah_id = k.id
            ORDER BY h.tanggal DESC, h.id DESC LIMIT 300
        """)
        libur_list = cursor.fetchall()
        cursor.execute("SELECT id, nama FROM sekolah ORDER BY nama")
        sekolah_list = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return render_template('admin_libur.html', libur_list=libur_list, sekolah_list=sekolah_list,
                           hari_ini=today_wib().isoformat())


@app.route('/admin/pembimbing', methods=['GET', 'POST'])
@admin_required
def admin_pembimbing():
    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('dashboard_admin'))
    cursor = conn.cursor(dictionary=True)
    ROLE_BOLEH = ('pembimbing_pkl', 'pembimbing_industri')
    try:
        cursor.execute("SELECT id, nama FROM sekolah ORDER BY nama")
        sekolah_opsi = cursor.fetchall()
        sekolah_ids = {k['id'] for k in sekolah_opsi}

        if request.method == 'POST':
            aksi = request.form.get('aksi', '')
            user_id = request.form.get('user_id', type=int)
            try:
                if aksi == 'tambah':
                    username = request.form.get('username', '').strip()
                    nama = request.form.get('nama', '').strip()
                    password = request.form.get('password', '')
                    role = request.form.get('role', '')
                    sekolah_id = request.form.get('sekolah_id', type=int)

                    if role not in ROLE_BOLEH or not username or not nama:
                        flash('Username, nama, dan role wajib diisi dengan benar!', 'danger')
                    elif len(password) < 6:
                        flash('Password minimal 6 karakter!', 'danger')
                    elif role == 'pembimbing_pkl' and sekolah_id not in sekolah_ids:
                        flash('Pembimbing PKL wajib dikaitkan dengan satu sekolah!', 'danger')
                    else:
                        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                        if cursor.fetchone():
                            flash(f'Username "{username}" sudah dipakai.', 'danger')
                        else:
                            cursor.execute("""
                                INSERT INTO users (username, password, nama, role, sekolah_id)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (username, generate_password_hash(password), nama, role,
                                  sekolah_id if role == 'pembimbing_pkl' else None))
                            conn.commit()
                            flash(f'Akun {nama} ({role}) berhasil dibuat.', 'success')

                elif aksi in ('toggle', 'reset', 'ubah_sekolah') and user_id:
                    cursor.execute("SELECT id, nama, role, is_active FROM users WHERE id = %s", (user_id,))
                    target = cursor.fetchone()
                    if not target or target['role'] not in ROLE_BOLEH:
                        flash('Akun pembimbing tidak ditemukan.', 'danger')
                    elif aksi == 'toggle':
                        baru = 0 if int(target['is_active'] if target['is_active'] is not None else 1) == 1 else 1
                        cursor.execute("UPDATE users SET is_active = %s WHERE id = %s", (baru, user_id))
                        conn.commit()
                        flash(f"Akun {target['nama']} {'dinonaktifkan' if baru == 0 else 'diaktifkan kembali'}.",
                              'warning' if baru == 0 else 'success')
                    elif aksi == 'reset':
                        pw = request.form.get('password_baru', '')
                        if len(pw) < 6:
                            flash('Password baru minimal 6 karakter!', 'danger')
                        else:
                            cursor.execute("UPDATE users SET password = %s WHERE id = %s",
                                           (generate_password_hash(pw), user_id))
                            conn.commit()
                            flash(f"Password {target['nama']} berhasil direset.", 'success')
                    else:  # ubah_sekolah
                        sekolah_id = request.form.get('sekolah_id', type=int)
                        if target['role'] != 'pembimbing_pkl':
                            flash('Hanya Pembimbing PKL yang terikat ke sekolah.', 'danger')
                        elif sekolah_id not in sekolah_ids:
                            flash('Sekolah tidak valid.', 'danger')
                        else:
                            cursor.execute("UPDATE users SET sekolah_id = %s WHERE id = %s", (sekolah_id, user_id))
                            # siswa bimbingan dari sekolah lama otomatis dilepas
                            cursor.execute("""
                                UPDATE siswa SET pembimbing_pkl_id = NULL
                                WHERE pembimbing_pkl_id = %s AND (sekolah_id IS NULL OR sekolah_id <> %s)
                            """, (user_id, sekolah_id))
                            conn.commit()
                            flash(f"Sekolah {target['nama']} berhasil diubah. Siswa bimbingan dari sekolah lama dilepas. Berlaku pada login berikutnya.", 'success')
                else:
                    flash('Aksi tidak valid.', 'danger')
            except mysql.connector.Error as e:
                conn.rollback()
                flash(f'Terjadi kesalahan database: {e}', 'danger')
            return redirect(url_for('admin_pembimbing'))

        cursor.execute("""
            SELECT u.id, u.username, u.nama, u.role, u.is_active, u.sekolah_id, k.nama AS nama_sekolah,
                   (SELECT COUNT(*) FROM siswa b WHERE b.pembimbing_pkl_id = u.id) AS jml_bimbingan
            FROM users u
            LEFT JOIN sekolah k ON u.sekolah_id = k.id
            WHERE u.role IN ('pembimbing_pkl', 'pembimbing_industri')
            ORDER BY u.role, k.nama, u.nama
        """)
        pembimbing_list = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return render_template('admin_pembimbing.html', pembimbing_list=pembimbing_list, sekolah_opsi=sekolah_opsi)

@app.route('/admin/pembimbing/<int:user_id>/bimbingan', methods=['GET', 'POST'])
@admin_required
def admin_bimbingan(user_id):
    """Tetapkan siswa mana saja yang dibimbing seorang pembimbing_pkl.

    Hanya siswa dari sekolah pembimbing tsb yang bisa dipilih. Satu siswa hanya
    punya satu pembimbing PKL; memilihnya di sini memindahkannya dari pembimbing lain.
    """
    conn = get_db_connection()
    if not conn:
        flash('Gagal terhubung ke database.', 'danger')
        return redirect(url_for('admin_pembimbing'))
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT u.id, u.nama, u.username, u.sekolah_id, k.nama AS nama_sekolah
            FROM users u LEFT JOIN sekolah k ON u.sekolah_id = k.id
            WHERE u.id = %s AND u.role = 'pembimbing_pkl'
        """, (user_id,))
        pembimbing = cursor.fetchone()
        if not pembimbing:
            flash('Pembimbing PKL tidak ditemukan.', 'danger')
            return redirect(url_for('admin_pembimbing'))
        if not pembimbing['sekolah_id']:
            flash('Atur sekolah pembimbing ini terlebih dahulu.', 'danger')
            return redirect(url_for('admin_pembimbing'))

        if request.method == 'POST':
            terpilih = {int(x) for x in request.form.getlist('siswa_id') if x.isdigit()}
            try:
                # Lepas semua bimbingan lama pembimbing ini, lalu pasang yang dicentang
                cursor.execute("UPDATE siswa SET pembimbing_pkl_id = NULL WHERE pembimbing_pkl_id = %s", (user_id,))
                if terpilih:
                    marks = ", ".join(["%s"] * len(terpilih))
                    cursor.execute(
                        f"UPDATE siswa SET pembimbing_pkl_id = %s "
                        f"WHERE sekolah_id = %s AND id IN ({marks})",
                        (user_id, pembimbing['sekolah_id'], *sorted(terpilih)))
                conn.commit()
                flash(f"Siswa bimbingan {pembimbing['nama']} berhasil disimpan.", 'success')
            except mysql.connector.Error as e:
                conn.rollback()
                flash(f'Terjadi kesalahan database: {e}', 'danger')
            return redirect(url_for('admin_bimbingan', user_id=user_id))

        cursor.execute("""
            SELECT s.id, s.nisn, s.kelas_jurusan, u.nama, s.pembimbing_pkl_id, g.nama AS nama_pembimbing_lain
            FROM siswa s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN users g ON s.pembimbing_pkl_id = g.id AND g.id <> %s
            WHERE s.sekolah_id = %s
            ORDER BY u.nama ASC
        """, (user_id, pembimbing['sekolah_id']))
        siswa_list = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return render_template('admin_bimbingan.html', pembimbing=pembimbing, siswa_list=siswa_list)


@app.route('/logout')
def logout():
    session.clear()
    flash('Anda telah keluar dari sistem.', 'info')
    return redirect(url_for('login'))

pastikan_skema()

if __name__ == '__main__':
    # Dengan reloader debug, hanya proses anak (yang melayani request) yang menjalankan penjadwal.
    if os.environ.get('FLASK_DEBUG') != '1' or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        pastikan_penjadwal_jalan()
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', port=int(os.environ.get('PORT', 5000)))
