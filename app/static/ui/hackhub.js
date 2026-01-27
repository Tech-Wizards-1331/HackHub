/* HackHub UI helpers (frontend-only). No backend coupling. */
(function () {
  function getPreferredTheme() {
    const stored = localStorage.getItem('hh-theme');
    if (stored === 'dark' || stored === 'light') return stored;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }

  function applyTheme(theme) {
    const html = document.documentElement;
    html.setAttribute('data-theme', theme);
    localStorage.setItem('hh-theme', theme);
    const icon = document.querySelector('[data-hh-theme-icon]');
    if (icon) icon.className = theme === 'dark' ? 'bi bi-moon-stars' : 'bi bi-sun';
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  }

  function ensureToastsContainer() {
    let el = document.getElementById('hh-toasts');
    if (!el) {
      el = document.createElement('div');
      el.id = 'hh-toasts';
      el.className = 'hh-toasts';
      document.body.appendChild(el);
    }
    return el;
  }

  function toast(message, variant) {
    const container = ensureToastsContainer();
    const t = document.createElement('div');
    t.className = 'hh-toast';

    const icon = document.createElement('div');
    icon.style.marginTop = '2px';

    let iconClass = 'bi bi-check-circle';
    if (variant === 'error' || variant === 'danger') iconClass = 'bi bi-x-circle';
    else if (variant === 'warning') iconClass = 'bi bi-exclamation-triangle';
    else if (variant === 'info') iconClass = 'bi bi-info-circle';

    icon.innerHTML = `<i class="${iconClass}"></i>`;

    const body = document.createElement('div');
    body.style.flex = '1';

    const title = document.createElement('div');
    title.style.fontWeight = '600';
    title.style.fontSize = '0.92rem';
    title.textContent = variant === 'error' ? 'Action failed' : variant === 'warning' ? 'Heads up' : variant === 'info' ? 'Info' : 'Done';

    const text = document.createElement('div');
    text.className = 'hh-muted';
    text.style.fontSize = '0.88rem';
    text.textContent = message;

    const close = document.createElement('button');
    close.className = 'hh-btn';
    close.style.padding = '0.35rem 0.5rem';
    close.innerHTML = '<i class="bi bi-x"></i>';
    close.addEventListener('click', function () { t.remove(); });

    body.appendChild(title);
    body.appendChild(text);

    t.appendChild(icon);
    t.appendChild(body);
    t.appendChild(close);

    container.appendChild(t);
    setTimeout(function () {
      if (t && t.parentNode) t.remove();
    }, 4200);
  }

  function bindSidebar() {
    const openBtn = document.querySelector('[data-hh-sidebar-open]');
    const closeBtn = document.querySelector('[data-hh-sidebar-close]');
    const overlay = document.querySelector('[data-hh-sidebar-overlay]');
    const sidebar = document.querySelector('[data-hh-sidebar]');

    function open() {
      if (!sidebar) return;
      sidebar.classList.remove('translate-x-[-110%]');
      sidebar.classList.add('translate-x-0');
      if (overlay) overlay.classList.remove('hidden');
    }

    function close() {
      if (!sidebar) return;
      sidebar.classList.add('translate-x-[-110%]');
      sidebar.classList.remove('translate-x-0');
      if (overlay) overlay.classList.add('hidden');
    }

    if (openBtn) openBtn.addEventListener('click', open);
    if (closeBtn) closeBtn.addEventListener('click', close);
    if (overlay) overlay.addEventListener('click', close);

    window.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
  }

  // Expose small API for pages
  window.HackHubUI = {
    applyTheme,
    toggleTheme,
    toast,
  };

  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(getPreferredTheme());

    const themeBtn = document.querySelector('[data-hh-theme-toggle]');
    if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

    bindSidebar();

    // Convert server flash messages into toasts (optional)
    document.querySelectorAll('[data-hh-flash]').forEach(function (el) {
      const variant = el.getAttribute('data-variant') || 'success';
      const msg = el.textContent || '';
      if (msg.trim()) toast(msg.trim(), variant);
      el.remove();
    });
  });
})();
