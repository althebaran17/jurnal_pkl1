-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Nov 15, 2026 at 06:33 PM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.0.30

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `db_jurnal_pkl`
--

-- --------------------------------------------------------

--
-- Table structure for table `absensi`
--

CREATE TABLE `absensi` (
  `id` int(11) NOT NULL,
  `siswa_id` int(11) NOT NULL,
  `tanggal` date NOT NULL,
  `status` enum('Hadir','Izin','Sakit','Alpa') NOT NULL,
  `keterangan` text DEFAULT NULL,
  `foto_bukti` varchar(255) DEFAULT NULL,
  `lokasi` varchar(255) DEFAULT NULL,
  `is_manual` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `laporan_harian`
--

CREATE TABLE `laporan_harian` (
  `id` int(11) NOT NULL,
  `siswa_id` int(11) NOT NULL,
  `tanggal` date DEFAULT NULL,
  `minggu_ke` int(11) DEFAULT NULL,
  `tanggal_mulai` date DEFAULT NULL,
  `tanggal_selesai` date DEFAULT NULL,
  `deskripsi_kegiatan` text NOT NULL,
  `foto_bukti` varchar(255) NOT NULL,
  `alasan_terlambat` text DEFAULT NULL,
  `status_validasi` enum('Pending','Disetujui','Revisi') DEFAULT 'Pending',
  `catatan_pembimbing` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `nilai_pkl`
--

CREATE TABLE `nilai_pkl` (
  `id` int(11) NOT NULL,
  `siswa_id` int(11) NOT NULL,
  `pembimbing_id` int(11) NOT NULL,
  `nilai_absensi` decimal(5,2) DEFAULT 0.00,
  `nilai_laporan` decimal(5,2) DEFAULT 0.00,
  `nilai_sikap` int(11) DEFAULT 0,
  `nilai_teknis` int(11) DEFAULT 0,
  `nilai_akhir` decimal(5,2) DEFAULT 0.00,
  `predikat` varchar(2) DEFAULT 'B',
  `catatan_pembimbing` text DEFAULT NULL,
  `created_at` datetime DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `pembimbing`
--

CREATE TABLE `pembimbing` (
  `id` int(11) NOT NULL,
  `user_id` int(11) NOT NULL,
  `nama_perusahaan` varchar(150) DEFAULT NULL,
  `jabatan` varchar(100) DEFAULT NULL,
  `divisi` varchar(100) DEFAULT NULL,
  `no_hp` varchar(20) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `alamat_perusahaan` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;


-- --------------------------------------------------------

--
-- Table structure for table `pengajuan_absensi`
--

CREATE TABLE `pengajuan_absensi` (
  `id` int(11) NOT NULL,
  `siswa_id` int(11) NOT NULL,
  `tanggal` date NOT NULL,
  `jenis` enum('Izin','Sakit','Terlambat') NOT NULL,
  `alasan` text NOT NULL,
  `bukti_file` varchar(255) DEFAULT NULL,
  `status_pengajuan` enum('Pending','Disetujui','Ditolak') DEFAULT 'Pending',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `sudah_dilihat` int(11) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `pengumuman_pembimbing`
--

CREATE TABLE `pengumuman_pembimbing` (
  `id` int(11) NOT NULL,
  `pesan` text NOT NULL,
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `sekolah_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;


-- --------------------------------------------------------

--
-- Table structure for table `sekolah`
--

CREATE TABLE `sekolah` (
  `id` int(11) NOT NULL,
  `nama` varchar(255) NOT NULL,
  `npsn` varchar(50) DEFAULT NULL,
  `alamat` text DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;


-- --------------------------------------------------------

--
-- Table structure for table `siswa`
--

CREATE TABLE `siswa` (
  `id` int(11) NOT NULL,
  `user_id` int(11) NOT NULL,
  `nisn` varchar(20) NOT NULL,
  `kelas_jurusan` varchar(50) DEFAULT NULL,
  `tgl_mulai_pkl` date DEFAULT NULL,
  `tgl_selesai_pkl` date DEFAULT NULL,
  `tempat_lahir` varchar(100) DEFAULT NULL,
  `tanggal_lahir` date DEFAULT NULL,
  `jenis_kelamin` enum('L','P') DEFAULT NULL,
  `no_hp` varchar(20) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `alamat` text DEFAULT NULL,
  `foto_profil` varchar(255) DEFAULT NULL,
  `sekolah_id` int(11) DEFAULT NULL,
  `pembimbing_pkl_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;


-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `id` int(11) NOT NULL,
  `username` varchar(50) NOT NULL,
  `password` varchar(255) NOT NULL,
  `nama` varchar(100) NOT NULL,
  `role` enum('pembimbing_industri','pembimbing_pkl','siswa','admin') NOT NULL,
  `is_active` tinyint(1) DEFAULT 1,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `sekolah_id` int(11) DEFAULT NULL,
  `totp_secret` varchar(64) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;


--
-- Indexes for dumped tables
--

--
-- Indexes for table `absensi`
--
ALTER TABLE `absensi`
  ADD PRIMARY KEY (`id`),
  ADD KEY `siswa_id` (`siswa_id`),
  ADD UNIQUE KEY `uq_absensi_siswa_tanggal` (`siswa_id`,`tanggal`);

--
-- Indexes for table `laporan_harian`
--
ALTER TABLE `laporan_harian`
  ADD PRIMARY KEY (`id`),
  ADD KEY `siswa_id` (`siswa_id`),
  ADD KEY `idx_siswa_tanggal` (`siswa_id`,`tanggal`);

--
-- Indexes for table `nilai_pkl`
--
ALTER TABLE `nilai_pkl`
  ADD PRIMARY KEY (`id`),
  ADD KEY `siswa_id` (`siswa_id`),
  ADD KEY `fk_nilai_users` (`pembimbing_id`);

--
-- Indexes for table `pembimbing`
--
ALTER TABLE `pembimbing`
  ADD PRIMARY KEY (`id`),
  ADD KEY `user_id` (`user_id`);

--
-- Indexes for table `pengajuan_absensi`
--
ALTER TABLE `pengajuan_absensi`
  ADD PRIMARY KEY (`id`),
  ADD KEY `siswa_id` (`siswa_id`),
  ADD KEY `idx_siswa_tanggal` (`siswa_id`,`tanggal`);

--
-- Indexes for table `pengumuman_pembimbing`
--
ALTER TABLE `pengumuman_pembimbing`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `sekolah`
--
ALTER TABLE `sekolah`
  ADD PRIMARY KEY (`id`);

--
-- Indexes for table `siswa`
--
ALTER TABLE `siswa`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `nisn` (`nisn`),
  ADD KEY `user_id` (`user_id`),
  ADD KEY `idx_siswa_sekolah` (`sekolah_id`),
  ADD KEY `idx_siswa_pembimbing_pkl` (`pembimbing_pkl_id`);

--
-- Indexes for table `users`
--
ALTER TABLE `users`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `username` (`username`),
  ADD KEY `idx_users_sekolah` (`sekolah_id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `absensi`
--
ALTER TABLE `absensi`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=25;

--
-- AUTO_INCREMENT for table `laporan_harian`
--
ALTER TABLE `laporan_harian`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=10;

--
-- AUTO_INCREMENT for table `nilai_pkl`
--
ALTER TABLE `nilai_pkl`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `pembimbing`
--
ALTER TABLE `pembimbing`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT for table `pengajuan_absensi`
--
ALTER TABLE `pengajuan_absensi`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=22;

--
-- AUTO_INCREMENT for table `pengumuman_pembimbing`
--
ALTER TABLE `pengumuman_pembimbing`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=9;

--
-- AUTO_INCREMENT for table `sekolah`
--
ALTER TABLE `sekolah`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT for table `siswa`
--
ALTER TABLE `siswa`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=15;

--
-- AUTO_INCREMENT for table `users`
--
ALTER TABLE `users`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=21;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `absensi`
--
ALTER TABLE `absensi`
  ADD CONSTRAINT `absensi_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `laporan_harian`
--
ALTER TABLE `laporan_harian`
  ADD CONSTRAINT `laporan_harian_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `nilai_pkl`
--
ALTER TABLE `nilai_pkl`
  ADD CONSTRAINT `fk_nilai_users` FOREIGN KEY (`pembimbing_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `nilai_pkl_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `nilai_pkl_ibfk_2` FOREIGN KEY (`pembimbing_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `pembimbing`
--
ALTER TABLE `pembimbing`
  ADD CONSTRAINT `pembimbing_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `pengajuan_absensi`
--
ALTER TABLE `pengajuan_absensi`
  ADD CONSTRAINT `pengajuan_absensi_ibfk_1` FOREIGN KEY (`siswa_id`) REFERENCES `siswa` (`id`) ON DELETE CASCADE;

--
-- Constraints for table `siswa`
--
ALTER TABLE `siswa`
  ADD CONSTRAINT `siswa_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;

--
-- Tabel pendukung (juga dibuat otomatis oleh aplikasi bila belum ada)
--
CREATE TABLE IF NOT EXISTS `hari_libur` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `tanggal` date NOT NULL,
  `keterangan` varchar(150) NOT NULL,
  `sekolah_id` int(11) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_hari_libur_tanggal` (`tanggal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `pengumuman_dibaca` (
  `user_id` int(11) NOT NULL,
  `pengumuman_id` int(11) NOT NULL,
  `dibaca_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`user_id`,`pengumuman_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `login_gagal` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `kunci` varchar(191) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `waktu` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_login_gagal_kunci_waktu` (`kunci`,`waktu`),
  KEY `idx_login_gagal_waktu` (`waktu`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
