#!/usr/bin/env bash
# Bersihkan repo jurnal_pkl1 dari file yang tidak seharusnya ada di Git.
# Skrip ini AMAN: hanya melepas file dari pelacakan Git (git rm --cached);
# file asli di komputermu tidak dihapus. Jalankan dari folder root repo.
set -e

# 1) pastikan .gitignore baru terpasang (salin gitignore.txt -> .gitignore dulu)
if ! grep -q "static/uploads/" .gitignore 2>/dev/null; then
  echo "Salin dulu: pastikan .gitignore dari paket ini terpasang"; exit 1
fi

# 2) lepas dari pelacakan Git
git rm -r --cached --ignore-unmatch \
  coba.py \
  fix_login.py \
  seed.py \
  update_db.py \
  BACA_DULU.txt \
  gitignore.txt \
  .env \
  db_jurnal_pkl.sql \
  db_jurnal_pkl_railway.sql \
  static.zip \
  jurnal_pkl1-main.zip \
  main \
  README.mdgit \
  static/uploads/profil

git add .gitignore .env.example README.md db_jurnal_pkl_schema.sql
echo
echo "Selesai. Tinjau dengan: git status"
echo "Lalu: git commit -m 'Bersihkan repo: hapus data pribadi, skrip berbahaya, dan arsip'"
echo
cat <<'CATATAN'
PENTING - file lama MASIH ada di riwayat (history) Git. Bila repo ini pernah/sedang publik:
  * anggap data di db_jurnal_pkl.sql (nama, email, nomor HP, hash password) dan foto profil SUDAH bocor;
  * hapus dari riwayat dengan git-filter-repo (WAJIB backup dulu, lalu force-push):
      pip install git-filter-repo
      git filter-repo --invert-paths \
        --path db_jurnal_pkl.sql --path db_jurnal_pkl_railway.sql --path static/uploads/profil \
        --path .env --path static.zip --path jurnal_pkl1-main.zip --path fix_login.py --path seed.py --path coba.py
      git push --force --all
  * ganti SECRET_KEY di Railway, dan minta pengguna mengganti password (siswa lama yang masih
    memakai NISN akan dipaksa ganti saat login berikutnya).
  * db_jurnal_pkl_railway.sql memuat alamat host database Railway dan perintah DROP DATABASE:
    JANGAN pernah diimpor ke database produksi. Pakai db_jurnal_pkl_schema.sql untuk referensi skema.
  * catatan: fix_login.py berisi perintah TRUNCATE untuk tabel users/siswa/absensi - jangan dijalankan.
CATATAN
