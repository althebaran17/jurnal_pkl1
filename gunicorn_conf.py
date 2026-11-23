"""Konfigurasi gunicorn: jalankan penyapu Alpa otomatis begitu worker siap.

Tanpa ini, thread penyapu baru hidup saat ada request PERTAMA setelah restart/deploy,
sehingga bila belum ada yang membuka web, Alpa jam 15:00 tertunda.
"""


def post_worker_init(worker):
    from auto_alpa import pastikan_penjadwal_jalan
    pastikan_penjadwal_jalan()
