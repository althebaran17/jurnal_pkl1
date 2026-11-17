-- --------------------------------------------------------
-- Host:                         caboose.proxy.rlwy.net
-- Server version:               8.4.13 - MySQL Community Server - GPL
-- Server OS:                    Linux
-- HeidiSQL Version:             12.22.0.7382
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;


-- Dumping database structure for railway
DROP DATABASE IF EXISTS `railway`;
CREATE DATABASE IF NOT EXISTS `railway` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `railway`;

-- Dumping structure for table railway.absensi
DROP TABLE IF EXISTS `absensi`;
CREATE TABLE IF NOT EXISTS `absensi` (
  `id` int NOT NULL AUTO_INCREMENT,
  `siswa_id` int NOT NULL,
  `tanggal` date NOT NULL,
  `status` enum('Hadir','Izin','Sakit','Alpa') COLLATE utf8mb4_general_ci NOT NULL,
  `keterangan` text COLLATE utf8mb4_general_ci,
  `foto_bukti` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `lokasi` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `is_manual` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `siswa_id` (`siswa_id`),
  KEY `idx_siswa_tanggal` (`siswa_id`,`tanggal`),
  CONSTRAINT `absensi_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=678 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.laporan_harian
DROP TABLE IF EXISTS `laporan_harian`;
CREATE TABLE IF NOT EXISTS `laporan_harian` (
  `id` int NOT NULL AUTO_INCREMENT,
  `siswa_id` int NOT NULL,
  `tanggal` date DEFAULT NULL,
  `minggu_ke` int DEFAULT NULL,
  `tanggal_mulai` date DEFAULT NULL,
  `tanggal_selesai` date DEFAULT NULL,
  `deskripsi_kegiatan` text COLLATE utf8mb4_general_ci NOT NULL,
  `foto_bukti` varchar(255) COLLATE utf8mb4_general_ci NOT NULL,
  `alasan_terlambat` text COLLATE utf8mb4_general_ci,
  `status_validasi` enum('Pending','Disetujui','Revisi') COLLATE utf8mb4_general_ci DEFAULT 'Pending',
  `catatan_pembimbing` text COLLATE utf8mb4_general_ci,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `siswa_id` (`siswa_id`),
  KEY `idx_siswa_tanggal` (`siswa_id`,`tanggal`),
  CONSTRAINT `laporan_harian_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.nilai_pkl
DROP TABLE IF EXISTS `nilai_pkl`;
CREATE TABLE IF NOT EXISTS `nilai_pkl` (
  `id` int NOT NULL AUTO_INCREMENT,
  `siswa_id` int NOT NULL,
  `pembimbing_id` int NOT NULL,
  `nilai_absensi` decimal(5,2) DEFAULT '0.00',
  `nilai_laporan` decimal(5,2) DEFAULT '0.00',
  `nilai_sikap` int DEFAULT '0',
  `nilai_teknis` int DEFAULT '0',
  `nilai_akhir` decimal(5,2) DEFAULT '0.00',
  `predikat` varchar(2) COLLATE utf8mb4_general_ci DEFAULT 'B',
  `catatan_pembimbing` text COLLATE utf8mb4_general_ci,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `siswa_id` (`siswa_id`),
  KEY `fk_nilai_users` (`pembimbing_id`),
  CONSTRAINT `fk_nilai_users` FOREIGN KEY (`pembimbing_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `nilai_pkl_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE,
  CONSTRAINT `nilai_pkl_ibfk_2` FOREIGN KEY (`pembimbing_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.pembimbing
DROP TABLE IF EXISTS `pembimbing`;
CREATE TABLE IF NOT EXISTS `pembimbing` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `nama_perusahaan` varchar(150) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `jabatan` varchar(100) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `divisi` varchar(100) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `no_hp` varchar(20) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `email` varchar(100) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `alamat_perusahaan` text COLLATE utf8mb4_general_ci,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `pembimbing_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.pengajuan_absensi
DROP TABLE IF EXISTS `pengajuan_absensi`;
CREATE TABLE IF NOT EXISTS `pengajuan_absensi` (
  `id` int NOT NULL AUTO_INCREMENT,
  `siswa_id` int NOT NULL,
  `tanggal` date NOT NULL,
  `jenis` enum('Izin','Sakit','Terlambat') COLLATE utf8mb4_general_ci NOT NULL,
  `alasan` text COLLATE utf8mb4_general_ci NOT NULL,
  `bukti_file` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `status_pengajuan` enum('Pending','Disetujui','Ditolak') COLLATE utf8mb4_general_ci DEFAULT 'Pending',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `sudah_dilihat` int DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `siswa_id` (`siswa_id`),
  KEY `idx_siswa_tanggal` (`siswa_id`,`tanggal`),
  CONSTRAINT `pengajuan_absensi_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=27 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.pengumuman_pembimbing
DROP TABLE IF EXISTS `pengumuman_pembimbing`;
CREATE TABLE IF NOT EXISTS `pengumuman_pembimbing` (
  `id` int NOT NULL AUTO_INCREMENT,
  `pesan` text COLLATE utf8mb4_general_ci NOT NULL,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `sekolah_id` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.sekolah
DROP TABLE IF EXISTS `sekolah`;
CREATE TABLE IF NOT EXISTS `sekolah` (
  `id` int NOT NULL AUTO_INCREMENT,
  `nama` varchar(255) COLLATE utf8mb4_general_ci NOT NULL,
  `npsn` varchar(50) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `alamat` text COLLATE utf8mb4_general_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.siswa
DROP TABLE IF EXISTS `siswa`;
CREATE TABLE IF NOT EXISTS `siswa` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `nisn` varchar(20) COLLATE utf8mb4_general_ci NOT NULL,
  `kelas_jurusan` varchar(50) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `tgl_mulai_pkl` date DEFAULT NULL,
  `tgl_selesai_pkl` date DEFAULT NULL,
  `tempat_lahir` varchar(100) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `tanggal_lahir` date DEFAULT NULL,
  `jenis_kelamin` enum('L','P') COLLATE utf8mb4_general_ci DEFAULT NULL,
  `no_hp` varchar(20) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `email` varchar(100) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `alamat` text COLLATE utf8mb4_general_ci,
  `foto_profil` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `sekolah_id` int DEFAULT NULL,
  `pembimbing_pkl_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `nisn` (`nisn`),
  KEY `user_id` (`user_id`),
  KEY `idx_siswa_sekolah` (`sekolah_id`),
  KEY `idx_siswa_pembimbing_pkl` (`pembimbing_pkl_id`),
  CONSTRAINT `siswa_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

-- Dumping structure for table railway.users
DROP TABLE IF EXISTS `users`;
CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) COLLATE utf8mb4_general_ci NOT NULL,
  `password` varchar(255) COLLATE utf8mb4_general_ci NOT NULL,
  `nama` varchar(100) COLLATE utf8mb4_general_ci NOT NULL,
  `role` enum('pembimbing_industri','pembimbing_pkl','siswa','admin') COLLATE utf8mb4_general_ci NOT NULL,
  `is_active` tinyint(1) DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `sekolah_id` int DEFAULT NULL,
  `totp_secret` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  KEY `idx_users_sekolah` (`sekolah_id`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data exporting was unselected.

/*!40103 SET TIME_ZONE=IFNULL(@OLD_TIME_ZONE, 'system') */;
/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40111 SET SQL_NOTES=IFNULL(@OLD_SQL_NOTES, 1) */;
