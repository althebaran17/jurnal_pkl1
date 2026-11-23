"""Pembatasan percobaan login (anti brute-force) yang disimpan di DATABASE.

Kenapa modul ini ada
--------------------
Versi lama memakai dict di memori proses dengan kunci "IP|username" dan batas
tetap 5 kali / 10 menit. Kelemahannya:

* hilang saat restart/deploy dan tidak dibagi antar worker;
* tidak pernah dibersihkan (bisa dibanjiri username acak);
* di balik proxy Railway IP terbaca sama untuk semua orang;
* pengguna yang mencoba banyak username berbeda (mis. NISN/NISN) tidak pernah terkunci;
* username beraksen ("ádmin") dianggap kunci berbeda padahal MySQL menganggapnya
  sama dengan "admin".

Cara kerja sekarang
-------------------
Setiap kegagalan dicatat di tabel `login_gagal` (kunci, waktu). Ada dua jenis kunci
yang dihitung TERPISAH:

* ``ip:<alamat>``      -> semua kegagalan dari satu IP (menahan penyemprotan banyak akun)
* ``u:<username>``     -> semua kegagalan terhadap satu akun dari IP mana pun
* ``2fa:<id user>``    -> kode Authenticator yang salah

Batasnya bertahap (dihitung dari kegagalan dalam 1 jam terakhir; kunci berlaku
sejak kegagalan TERAKHIR):

    akun : 5-6 gagal -> kunci 5 menit | 7-9 gagal -> 15 menit | 10+ gagal -> 60 menit
    IP   : 10-19 gagal -> 5 menit    | 20-29 gagal -> 15 menit | 30+ gagal -> 60 menit

E-Jurnal dipakai siswa di tempat PKL lewat HP masing-masing, jadi satu IP umumnya = satu
perangkat (atau segelintir siswa di WiFi perusahaan yang sama) -> batas IP dibuat ketat.
Bila nanti ada IP bersama yang dipakai banyak orang, longgarkan BATAS_IP.
"""
import unicodedata
from datetime import timedelta
from math import ceil

from config import get_db_connection
from waktu import now_wib

def _sekarang():
    """Waktu WIB TANPA tzinfo. Kolom DATETIME MySQL tidak menyimpan zona, nilai yang dibaca
    kembali berupa datetime 'naive'; mencampurnya dengan datetime ber-tzinfo menimbulkan
    TypeError saat dikurangkan."""
    return now_wib().replace(tzinfo=None)


JENDELA_DETIK = 3600          # kegagalan yang lebih tua dari ini tidak dihitung
SIMPAN_DETIK = 86400          # baris yang lebih tua dari ini dihapus

# (jumlah gagal dalam jendela, lama kunci detik) - URUT MENURUN
BATAS_AKUN = ((10, 3600), (7, 900), (5, 300))
BATAS_IP = ((30, 3600), (20, 900), (10, 300))

_tabel_siap = False


def normalisasi_username(nama):
    """Samakan varian penulisan: huruf besar/kecil, aksen (á -> a), spasi, karakter tak terlihat."""
    teks = unicodedata.normalize('NFKD', str(nama or ''))
    teks = ''.join(c for c in teks if unicodedata.category(c)[0] not in 'MCZ')
    return teks.casefold()[:100]


def kunci_username(nama):
    return 'u:' + normalisasi_username(nama)


def kunci_ip(alamat):
    return 'ip:' + (str(alamat or 'tidak-diketahui'))[:64]


def kunci_2fa(user_id):
    return '2fa:' + str(user_id)


def format_sisa(detik):
    """'3 menit' / '45 detik' untuk pesan ke pengguna."""
    if detik < 60:
        return f'{max(int(detik), 1)} detik'
    return f'{int(ceil(detik / 60))} menit'


def _pastikan_tabel(conn):
    global _tabel_siap
    if _tabel_siap:
        return
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS login_gagal (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                kunci VARCHAR(191) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
                waktu DATETIME NOT NULL,
                INDEX idx_login_gagal_kunci_waktu (kunci, waktu),
                INDEX idx_login_gagal_waktu (waktu)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        _tabel_siap = True
    finally:
        cur.close()


def _buka():
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        _pastikan_tabel(conn)
    except Exception as e:
        print(f"[LOGIN GAGAL] tabel login_gagal tidak siap: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return None
    return conn


def _sisa_satu(cur, kunci, sekarang):
    tingkat = BATAS_IP if kunci.startswith('ip:') else BATAS_AKUN
    cur.execute(
        "SELECT COUNT(*) AS n, MAX(waktu) AS terakhir FROM login_gagal "
        "WHERE kunci = %s AND waktu >= %s",
        (kunci, sekarang - timedelta(seconds=JENDELA_DETIK)))
    baris = cur.fetchone() or {}
    n = baris.get('n') or 0
    terakhir = baris.get('terakhir')
    if not terakhir:
        return 0
    for batas, durasi in tingkat:
        if n >= batas:
            sisa = (terakhir + timedelta(seconds=durasi) - sekarang).total_seconds()
            return max(0, int(ceil(sisa)))
    return 0


def sisa_kunci(daftar_kunci):
    """Detik tersisa dari kunci TERPANJANG di daftar (0 = tidak terkunci)."""
    conn = _buka()
    if conn is None:
        return 0
    cur = conn.cursor(dictionary=True)
    try:
        sekarang = _sekarang()
        return max((_sisa_satu(cur, k, sekarang) for k in set(daftar_kunci)), default=0)
    except Exception as e:
        print(f"[LOGIN GAGAL] gagal membaca status kunci: {e}")
        return 0
    finally:
        cur.close()
        conn.close()


def catat_gagal(daftar_kunci):
    conn = _buka()
    if conn is None:
        return
    cur = conn.cursor()
    try:
        sekarang = _sekarang()
        for k in set(daftar_kunci):
            cur.execute("INSERT INTO login_gagal (kunci, waktu) VALUES (%s, %s)", (k, sekarang))
        # pembersihan baris lama supaya tabel tidak membengkak
        cur.execute("DELETE FROM login_gagal WHERE waktu < %s LIMIT 500",
                    (sekarang - timedelta(seconds=SIMPAN_DETIK),))
        conn.commit()
    except Exception as e:
        print(f"[LOGIN GAGAL] gagal mencatat kegagalan: {e}")
    finally:
        cur.close()
        conn.close()


def reset_gagal(daftar_kunci):
    """Hapus hitungan setelah login berhasil. Jangan sertakan kunci IP."""
    conn = _buka()
    if conn is None:
        return
    cur = conn.cursor()
    try:
        for k in set(daftar_kunci):
            cur.execute("DELETE FROM login_gagal WHERE kunci = %s", (k,))
        conn.commit()
    except Exception as e:
        print(f"[LOGIN GAGAL] gagal mereset hitungan: {e}")
    finally:
        cur.close()
        conn.close()
