/* Responsive E-Jurnal PKL: tombol ☰ untuk sidebar + tabel yang bisa digeser. */
(function () {
    'use strict';
    var BREAKPOINT = 992;

    function init() {
        var sidebar = document.querySelector('.sidebar');
        var navbar = document.querySelector('.navbar');

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
            btn.addEventListener('click', function () {
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
                document.documentElement.style.setProperty('--navbar-h', navbar.offsetHeight + 'px');
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

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
