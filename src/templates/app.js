// Theme toggle: persisted in localStorage, applied pre-paint by the inline
// snippet in each page's <head>. Button flips light/dark.
(function () {
  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    var btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  }
  function current() {
    var stored = localStorage.getItem('bt-theme');
    if (stored === 'light' || stored === 'dark') return stored;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  document.addEventListener('DOMContentLoaded', function () {
    apply(current());
    var btn = document.getElementById('theme-toggle');
    if (btn) btn.addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      localStorage.setItem('bt-theme', next);
      apply(next);
    });
    // Drawer: hamburger opens the left side drawer; scrim, close button and
    // Esc close it. Identical behavior at every viewport width (ticket #12).
    var drawer = document.getElementById('drawer');
    var menuBtn = document.getElementById('menu-toggle');
    if (drawer && menuBtn) {
      function setOpen(open) {
        drawer.classList.toggle('open', open);
        document.getElementById('scrim').classList.toggle('show', open);
        menuBtn.setAttribute('aria-expanded', String(open));
        if (open) drawer.focus();
        else menuBtn.focus();
      }
      menuBtn.addEventListener('click', function () {
        setOpen(!drawer.classList.contains('open'));
      });
      document.getElementById('scrim').addEventListener('click', function () {
        setOpen(false);
      });
      document.getElementById('drawer-close').addEventListener('click', function () {
        setOpen(false);
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && drawer.classList.contains('open')) setOpen(false);
      });
    }
    var path = location.pathname;
    document.querySelectorAll('#drawer nav a').forEach(function (a) {
      var href = a.getAttribute('href').split('?')[0];
      if (href === path || (path === '/' && href === '/searches')) a.classList.add('active');
    });
  });
})();

// Advanced toggle: shows/hides the Bargain Search form on /search.
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('advanced-toggle');
    var panel = document.getElementById('advanced');
    if (!btn || !panel) return;
    btn.addEventListener('click', function () {
      var show = panel.hasAttribute('hidden');
      if (show) panel.removeAttribute('hidden');
      else panel.setAttribute('hidden', '');
      btn.setAttribute('aria-expanded', String(show));
    });
  });
})();

// Description dialog: "Edit description" buttons open the shared <dialog>
// pre-filled with the listing's current authored text.
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var dlg = document.getElementById('desc-dialog');
    if (!dlg) return;
    document.querySelectorAll('.edit-desc').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.getElementById('dlg-listing-id').value = btn.dataset.listingId;
        document.getElementById('dlg-text').value = btn.dataset.current || '';
        dlg.showModal();
      });
    });
    document.getElementById('dlg-cancel').addEventListener('click', function () {
      dlg.close();
    });
  });
})();

// Liveness sweep: on /search, poll /liveness until the background sweep
// finishes; if it found any "no longer available" listings the freshly
// rendered page didn't show yet, reload once so the dead chips appear.
// Converges because after the reload the server-rendered dead count equals
// the sweep result, so no second reload fires.
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    if (location.pathname !== '/search') return;
    var rendered = document.querySelectorAll('li.card .dead').length;
    var timer = setInterval(function () {
      fetch('/liveness?id=' + encodeURIComponent(new URLSearchParams(location.search).get('id') || ''))
        .then(function (r) { return r.json(); })
        .then(function (s) {
          if (!s.done) return;
          clearInterval(timer);
          if ((s.dead || []).length !== rendered) location.reload();
        })
        .catch(function () {});
    }, 4000);
  });
})();
