import os
import warnings

import waktu  # noqa: F401  (memaksa zona waktu WIB sedini mungkin)
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

# Memuat variabel dari file .env
load_dotenv()

class Config:
    # Secret key untuk Flask session (diambil dari .env atau railway)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-only-ganti-lewat-env-SECRET_KEY'

    # Konfigurasi Database MySQL (Mendukung format DB_... maupun format Railway MYSQL_...)
    MYSQL_HOST = os.environ.get('DB_HOST') or os.environ.get('MYSQLHOST') or 'localhost'
    MYSQL_USER = os.environ.get('DB_USER') or os.environ.get('MYSQLUSER') or 'root'
    MYSQL_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('MYSQLPASSWORD') or ''
    MYSQL_DB = os.environ.get('DB_NAME') or os.environ.get('MYSQL_DATABASE') or os.environ.get('MYSQLDATABASE') or 'db_jurnal_pkl'
    
    # Mengambil DB_PORT / MYSQLPORT secara aman dari error string
    port_val = os.environ.get('DB_PORT') or os.environ.get('MYSQLPORT') or 3306
    try:
        MYSQL_PORT = int(str(port_val).replace('${MYSQLPORT}', '3306').replace('${PORT}', '3306'))
    except (ValueError, TypeError):
        MYSQL_PORT = 3306

    # Cookie sesi & keamanan HTTP
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PROJECT_ID'))
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 Jam

    # Pengaturan Upload File (Path Absolut)
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

if Config.SECRET_KEY.startswith('dev-only') and Config.SESSION_COOKIE_SECURE:
    warnings.warn('SECRET_KEY belum diatur di environment produksi! Sesi bisa dipalsukan.', RuntimeWarning)


def get_db_connection():
    """Fungsi pembantu untuk membuka koneksi ke database MySQL."""
    try:
        connection = mysql.connector.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB,
            port=Config.MYSQL_PORT
        )
        if connection.is_connected():
            # Server Railway berjalan di UTC. Paksa sesi MySQL ke WIB supaya NOW(),
            # CURRENT_TIMESTAMP, dan kolom created_at tercatat dengan jam WIB.
            try:
                cur = connection.cursor()
                cur.execute("SET time_zone = '+07:00'")
                cur.close()
            except Error as e:
                print(f"[MYSQL] gagal set time_zone WIB: {e}")
            return connection
    except Error as e:
        print(f"[MYSQL ERROR]: {e}")
    return None


if __name__ == '__main__':
    conn = get_db_connection()
    if conn and conn.is_connected():
        print("[SUCCESS] Koneksi database BERHASIL!")
        conn.close()
    else:
        print("[FAILED] Gagal terhubung ke database. Periksa konfigurasi MySQL Anda.")