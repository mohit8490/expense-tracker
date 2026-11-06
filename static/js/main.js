// Dark-mode toggle (remembered in localStorage)
(function () {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  const icon = btn.querySelector('i');
  const apply = (t) => {
    document.documentElement.setAttribute('data-bs-theme', t);
    icon.className = t === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
    document.dispatchEvent(new CustomEvent('themechange', { detail: t }));
  };
  apply(localStorage.getItem('theme') || 'light');
  btn.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', next);
    apply(next);
  });
})();

// Confirm before destructive actions: <form data-confirm="message">
document.addEventListener('submit', (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !confirm(msg)) e.preventDefault();
});

// Chart.js defaults follow the theme
function chartTextColor() {
  return document.documentElement.getAttribute('data-bs-theme') === 'dark' ? '#cbd5e1' : '#475569';
}
function applyChartDefaults() {
  if (window.Chart) {
    Chart.defaults.color = chartTextColor();
    Chart.defaults.borderColor = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? '#334155' : '#e2e8f0';
  }
}
applyChartDefaults();
document.addEventListener('themechange', () => {
  applyChartDefaults();
  if (window.Chart) Object.values(Chart.instances).forEach(c => { c.update(); });
});
