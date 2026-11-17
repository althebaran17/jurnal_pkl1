/* Responsive E-Jurnal PKL: Tombol ☰ untuk sidebar + tabel yang bisa digeser */
(function () {
    'use strict';
    var BREAKPOINT = 992;

    function init() {
        var sidebar = document.querySelector('.sidebar');
        var navbar = document.querySelector('.navbar');

        // Pastikan tombol toggle hanya dibuat sekali
        if (sidebar && navbar && !document.querySelector('.menu-toggle')) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'menu-toggle';
            btn.setAttribute('aria-label', 'Buka menu');
            btn.setAttribute('aria-expanded', 'false');
            btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg>';
            
            navbar.insertBefore(btn, navbar.firstChild);

            var overlay = document.createElement('div');
            overlay.className = 'sidebar-overlay';
            document.body.appendChild(overlay);

            var setOpen = function (open) {
                document.body.classList.toggle('sidebar-open', open);
                btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            };

            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                setOpen(!document.body.classList.contains('sidebar-open'));
            });

            overlay.addEventListener('click', function () { setOpen(false); });
            document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
            
            sidebar.addEventListener('click', function (e) {
                if (e.target.closest('a')) setOpen(false);
            });

            window.addEventListener('resize', function () {
                if (window.innerWidth > BREAKPOINT) setOpen(false);
            });
        }

        // Ukur tinggi header (fixed di mobile) supaya konten tidak tertutup
        if (navbar) {
            var ukur = function () {
                var h = navbar.offsetHeight || 64;
                document.documentElement.style.setProperty('--navbar-h', h + 'px');
            };
            ukur();
            window.addEventListener('resize', ukur);
            window.addEventListener('load', ukur);
            if (window.ResizeObserver) new ResizeObserver(ukur).observe(navbar);
        }

        // Bungkus tabel agar bisa digeser horizontal di layar sempit
        document.querySelectorAll('table').forEach(function (t) {
            if (t.closest('.table-container, .adm-scroll, .table-scroll, .no-scroll-wrap')) return;
            var wrap = document.createElement('div');
            wrap.className = 'table-scroll';
            t.parentNode.insertBefore(wrap, t);
            wrap.appendChild(t);
        });
    }

    // Jam WIB (Asia/Jakarta)
    function initJamWib() {
        // Halaman login tidak memiliki sidebar. Jika tidak ada sidebar, batalkan fungsi (jam tidak akan dibuat).
        var sidebar = document.querySelector('.sidebar');
        if (!sidebar) return; 

        if (document.querySelector('.wib-clock')) return;
        var fmtJam = new Intl.DateTimeFormat('id-ID', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Asia/Jakarta'
        });
        var fmtTgl = new Intl.DateTimeFormat('id-ID', {
            weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Jakarta'
        });
        var el = document.createElement('div');
        el.className = 'wib-clock wib-clock-sidebar';
        el.setAttribute('title', 'Waktu Indonesia Barat (WIB)');
        el.innerHTML = '<span class="wib-date"></span><span class="wib-time"></span><span class="wib-zone">WIB</span>';
        
        sidebar.appendChild(el);

        var tgl = el.querySelector('.wib-date'), jam = el.querySelector('.wib-time');
        var tick = function () {
            var d = new Date();
            if (jam) jam.textContent = fmtJam.format(d).replace(/\./g, ':');
            if (tgl) tgl.textContent = fmtTgl.format(d);
        };
        tick();
        setInterval(tick, 1000);
    }

    function initAll() { init(); initJamWib(); }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAll);
    else initAll();
})();