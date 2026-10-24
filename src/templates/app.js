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
    var path = location.pathname;
    document.querySelectorAll('.navbar .links a').forEach(function (a) {
      var href = a.getAttribute('href').split('?')[0];
      if (href === path || (path === '/' && href === '/searches')) a.classList.add('active');
    });
  });
})();
