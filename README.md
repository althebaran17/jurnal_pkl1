# E-Jurnal PKL

Aplikasi Flask + MySQL untuk jurnal, absensi, dan penilaian PKL (multi-sekolah).

## Menjalankan lokal
1. `pip install -r requirements.txt`
2. Salin `.env.example` menjadi `.env`, isi koneksi database dan `SECRET_KEY`.
3. Impor `db_jurnal_pkl_schema.sql` ke MySQL (hanya skema, tanpa data).
4. `flask --app app run` (atau `gunicorn app:app -c gunicorn_conf.py`).

## Deploy (Railway)
Variabel wajib: `SECRET_KEY` (>= 32 karakter; buat dengan
`python -c "import secrets; print(secrets.token_hex(32))"`) dan `ADMIN_SETUP_TOKEN`.
Opsional: `TRUST_PROXY_HOPS` (default 1).

- Admin 2FA: `flask --app app admin-2fa <username>`
- Cek Alpa otomatis sebelum aktif: `flask --app app auto-alpa --dry-run`

## Database yang sudah berjalan (migrasi)
- Multi-sekolah + admin: `python migrasi_multi_sekolah.py --dry-run` (backup dulu).
- Cegah presensi ganda (skema baru sudah menyertakannya):
  ```sql
  SELECT siswa_id, tanggal, COUNT(*) c FROM absensi GROUP BY siswa_id, tanggal HAVING c > 1;
  DELETE a FROM absensi a JOIN absensi b ON a.siswa_id=b.siswa_id AND a.tanggal=b.tanggal AND a.id<>b.id
   WHERE (a.status='Alpa' AND b.status<>'Alpa') OR (a.status=b.status AND a.id>b.id);
  ALTER TABLE absensi ADD UNIQUE KEY uq_absensi_siswa_tanggal (siswa_id, tanggal);
  ```

## Catatan repo
- Jangan commit `.env`, dump database berisi data, atau isi `uploads/`.
- Bila repo lama pernah publik, jalankan `bersihkan_repo.sh` dan bersihkan riwayat Git
  (`git filter-repo`), serta ganti `SECRET_KEY` dan password database.
- Video latar login ada di `static/video/bg-login.mp4` (bila dihapus, halaman login tetap jalan).
