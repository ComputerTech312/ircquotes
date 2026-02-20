// Dark mode toggle functionality for ircquotes
// Maintains bash.org aesthetic while providing dark theme option

function toggleDarkMode() {
    const body = document.body;
    const html = document.documentElement;
    const isDark = body.classList.contains('dark-theme') || html.classList.contains('dark-theme');
    
    if (isDark) {
        body.classList.remove('dark-theme');
        html.classList.remove('dark-theme');
        localStorage.setItem('theme', 'light');
        updateToggleButton(false);
    } else {
        body.classList.add('dark-theme');
        html.classList.add('dark-theme');
        localStorage.setItem('theme', 'dark');
        updateToggleButton(true);
    }
}

function updateToggleButton(isDark) {
    const toggleBtn = document.getElementById('theme-toggle');
    if (toggleBtn) {
        toggleBtn.textContent = isDark ? '☀' : '🌙';
        toggleBtn.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
    }
}

// Initialize theme on page load
document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
        document.body.classList.add('dark-theme');
        document.documentElement.classList.add('dark-theme');
        updateToggleButton(true);
    } else {
        document.body.classList.remove('dark-theme');
        document.documentElement.classList.remove('dark-theme');
        updateToggleButton(false);
    }
});