"""Migrasi: multi-sekolah + role admin untuk E-Jurnal PKL.

Aman dijalankan berulang (idempotent). Jalankan dari folder proyek:

    python migrasi_multi_sekolah.py                      # migrasi saja
    python migrasi_multi_sekolah.py --admin USERNAME     # + jadikan USERNAME admin
                                                         #   (akun dibuat jika belum ada, password ditanya)
    python migrasi_multi_sekolah.py --dry-run            # hanya tampilkan rencana

BACKUP DATABASE DULU (mysqldump) sebelum menjalankan.

Yang dilakukan:
 1. Tabel `sekolah` (id, nama, npsn, alamat).
 2. Kolom `siswa.sekolah_id`, `users.sekolah_id`, `pengumuman_pembimbing.sekolah_id`.
 3. Isi tabel sekolah dari teks `siswa.sekolah` yang sudah ada (dikelompokkan tanpa
    membedakan huruf besar/kecil & spasi berlebih), lalu isi `siswa.sekolah_id`.
 4. Tambah nilai 'admin' ke `users.role` bila kolom itu bertipe ENUM.
 5. (opsional) buat / promosikan akun admin.

CATATAN: akun pembimbing_pkl yang sudah ada BELUM punya sekolah. Admin harus mengaitkannya
lewat menu "Kelola Pembimbing"; selama belum, akun itu tidak bisa login.
Pengumuman lama dibiarkan sekolah_id = NULL (= tampil untuk semua sekolah).
"""
import argparse
import getpass
import re
import sys

from werkzeug.security import generate_password_hash

from config import Config, get_db_connection


def kolom_ada(cur, tabel, kolom):
    cur.execute(
        "SELECT COUNT(*) AS n FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
        (Config.MYSQL_DB, tabel, kolom))
    return cur.fetchone()['n'] > 0


def tabel_ada(cur, tabel):
    cur.execute(
        "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
        (Config.MYSQL_DB, tabel))
    return cur.fetchone()['n'] > 0


def normal(teks):
    return re.sub(r'\s+', ' ', (teks or '').strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--admin', metavar='USERNAME')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    conn = get_db_connection()
    if not conn:
        sys.exit('Tidak bisa terhubung ke database (cek .env).')
    cur = conn.cursor(dictionary=True)

    def jalan(sql, params=None):
        print('  SQL>', ' '.join(sql.split()))
        if not args.dry_run:
            cur.execute(sql, params or ())

    try:
        print('1. Tabel sekolah')
        if not tabel_ada(cur, 'sekolah'):
            jalan("""CREATE TABLE sekolah (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        nama VARCHAR(150) NOT NULL,
                        npsn VARCHAR(20) NULL,
                        alamat VARCHAR(255) NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_sekolah_nama (nama)
                     ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        else:
            print('  sudah ada')

        print('2. Kolom sekolah_id')
        for tabel in ('siswa', 'users', 'pengumuman_pembimbing'):
            if not kolom_ada(cur, tabel, 'sekolah_id'):
                jalan(f"ALTER TABLE {tabel} ADD COLUMN sekolah_id INT NULL")
                jalan(f"ALTER TABLE {tabel} ADD INDEX idx_{tabel}_sekolah (sekolah_id)")
            else:
                print(f'  {tabel}.sekolah_id sudah ada')

        print('3. Isi sekolah dari teks siswa.sekolah')
        if kolom_ada(cur, 'siswa', 'sekolah_id'):
            cur.execute("SELECT id, sekolah FROM siswa WHERE sekolah_id IS NULL AND sekolah IS NOT NULL AND TRIM(sekolah) <> ''")
        else:  # dry-run sebelum kolom dibuat
            cur.execute("SELECT id, sekolah FROM siswa WHERE sekolah IS NOT NULL AND TRIM(sekolah) <> ''")
        baris = cur.fetchall()
        peta = {}
        for b in baris:
            peta.setdefault(normal(b['sekolah']).lower(), []).append(b)
        for kunci, anggota in sorted(peta.items()):
            nama = normal(anggota[0]['sekolah'])
            print(f'  "{nama}" -> {len(anggota)} siswa')
            if args.dry_run:
                continue
            cur.execute("SELECT id FROM sekolah WHERE LOWER(nama) = %s", (kunci,))
            row = cur.fetchone()
            if row:
                sid = row['id']
            else:
                cur.execute("INSERT INTO sekolah (nama) VALUES (%s)", (nama,))
                sid = cur.lastrowid
            for b in anggota:
                cur.execute("UPDATE siswa SET sekolah_id = %s, sekolah = %s WHERE id = %s", (sid, nama, b['id']))

        print("4. users.role -> tambah 'admin'")
        cur.execute(
            "SELECT COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'users' AND column_name = 'role'", (Config.MYSQL_DB,))
        info = cur.fetchone()
        tipe = info['COLUMN_TYPE']
        if tipe.lower().startswith('enum(') and "'admin'" not in tipe:
            baru = tipe[:-1] + ",'admin')"
            null = 'NULL' if info['IS_NULLABLE'] == 'YES' else 'NOT NULL'
            default = f" DEFAULT '{info['COLUMN_DEFAULT']}'" if info['COLUMN_DEFAULT'] is not None else ''
            jalan(f"ALTER TABLE users MODIFY COLUMN role {baru} {null}{default}")
        else:
            print(f'  tidak perlu diubah (tipe: {tipe})')

        if args.admin:
            print(f"5. Akun admin '{args.admin}'")
            cur.execute("SELECT id, role FROM users WHERE username = %s", (args.admin,))
            u = cur.fetchone()
            if u:
                jalan("UPDATE users SET role = 'admin', sekolah_id = NULL WHERE id = %s", (u['id'],))
            elif not args.dry_run:
                pw = getpass.getpass('Password admin baru (min 8 karakter): ')
                if len(pw) < 8 or pw != getpass.getpass('Ulangi password: '):
                    sys.exit('Password tidak valid / tidak sama. Dibatalkan, tidak ada perubahan.')
                nama = input('Nama lengkap admin: ').strip() or 'Administrator'
                cur.execute("INSERT INTO users (username, password, nama, role) VALUES (%s, %s, %s, 'admin')",
                            (args.admin, generate_password_hash(pw), nama))
            else:
                print('  (akun belum ada; akan dibuat)')

        if args.dry_run:
            print('\nDRY-RUN: tidak ada perubahan yang disimpan.')
            conn.rollback()
        else:
            conn.commit()
            print('\nSelesai. Perubahan disimpan.')
    except Exception:
        conn.rollback()
        print('\nGAGAL, semua perubahan data dibatalkan (perubahan struktur MySQL tidak bisa di-rollback).')
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
