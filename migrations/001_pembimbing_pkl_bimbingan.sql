-- Penetapan siswa bimbingan untuk Pembimbing PKL.
-- app.py menjalankan perintah ini otomatis saat start bila kolom belum ada;
-- file ini disediakan bila Anda lebih suka menjalankannya manual.
ALTER TABLE siswa
  ADD COLUMN pembimbing_pkl_id INT NULL,
  ADD INDEX idx_siswa_pembimbing_pkl (pembimbing_pkl_id);

-- Contoh: tetapkan semua siswa SMK tertentu ke satu pembimbing (ganti id sesuai data Anda)
-- UPDATE siswa SET pembimbing_pkl_id = 12 WHERE sekolah_id = 3;

-- (Opsional, disarankan) cegah Alpa ganda bila beberapa proses berjalan bersamaan.
-- Jalankan HANYA setelah memastikan tidak ada duplikat:
--   SELECT siswa_id, tanggal, COUNT(*) FROM absensi GROUP BY siswa_id, tanggal HAVING COUNT(*) > 1;
-- ALTER TABLE absensi ADD UNIQUE KEY uq_absensi_siswa_tanggal (siswa_id, tanggal);
