"""
Alibi Shared Navigation Bar
Injected into every FastAPI-served HTML page for uniform navigation.
"""


def get_nav_css():
    """CSS for the nav bar — injected into <head>"""
    return """
    /* ── Alibi Nav Bar ── */
    .alibi-nav {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 9999;
        background: rgba(17, 24, 39, 0.95);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(255,255,255,0.08);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    .alibi-nav-inner {
        max-width: 1200px;
        margin: 0 auto;
        display: flex;
        align-items: center;
        height: 52px;
        padding: 0 16px;
        gap: 4px;
    }
    .alibi-nav-brand {
        color: #fff;
        font-weight: 700;
        font-size: 16px;
        text-decoration: none;
        margin-right: 16px;
        white-space: nowrap;
        letter-spacing: -0.3px;
    }
    .alibi-nav-links {
        display: flex;
        align-items: center;
        gap: 2px;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        flex: 1;
    }
    .alibi-nav-links::-webkit-scrollbar { display: none; }
    .alibi-nav-link {
        color: rgba(255,255,255,0.55);
        text-decoration: none;
        font-size: 13px;
        font-weight: 500;
        padding: 6px 12px;
        border-radius: 6px;
        white-space: nowrap;
        transition: all 0.15s ease;
    }
    .alibi-nav-link:hover {
        color: rgba(255,255,255,0.9);
        background: rgba(255,255,255,0.08);
    }
    .alibi-nav-link.active {
        color: #fff;
        background: rgba(99, 102, 241, 0.35);
    }
    .alibi-nav-sep {
        width: 1px;
        height: 20px;
        background: rgba(255,255,255,0.1);
        margin: 0 6px;
        flex-shrink: 0;
    }
    .alibi-nav-user {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-left: auto;
        flex-shrink: 0;
    }
    .alibi-nav-user-name {
        color: rgba(255,255,255,0.7);
        font-size: 12px;
        font-weight: 500;
    }
    .alibi-nav-user-role {
        color: rgba(99, 102, 241, 0.9);
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        background: rgba(99, 102, 241, 0.15);
        padding: 2px 8px;
        border-radius: 4px;
    }
    .alibi-nav-logout {
        color: rgba(255,255,255,0.4);
        background: none;
        border: 1px solid rgba(255,255,255,0.1);
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.15s ease;
    }
    .alibi-nav-logout:hover {
        color: #fff;
        border-color: rgba(255,255,255,0.3);
        background: rgba(255,255,255,0.05);
    }
    /* Push page content below fixed nav */
    .alibi-nav-spacer { height: 52px; }

    @media (max-width: 640px) {
        .alibi-nav-inner { padding: 0 10px; gap: 2px; }
        .alibi-nav-brand { font-size: 14px; margin-right: 8px; }
        .alibi-nav-link { font-size: 12px; padding: 5px 8px; }
        .alibi-nav-user-name { display: none; }
        .alibi-nav-user-role { display: none; }
    }
    """


def get_nav_html(active_page=""):
    """HTML for the nav bar — injected after <body>.
    active_page: one of 'home', 'camera', 'history', 'insights',
                 'watchlist', 'vehicles', 'training', 'console', 'docs'
    """
    def cls(page):
        return "alibi-nav-link active" if page == active_page else "alibi-nav-link"

    return f"""
    <nav class="alibi-nav" id="alibi-nav">
        <div class="alibi-nav-inner">
            <a href="/" class="alibi-nav-brand">Alibi</a>
            <div class="alibi-nav-links">
                <a href="/camera/secure-stream" class="{cls('camera')}">Camera</a>
                <a href="/camera/history" class="{cls('history')}">History</a>
                <a href="/camera/insights" class="{cls('insights')}">Insights</a>
                <a href="/camera/training" class="{cls('training')}">Training</a>
                <div class="alibi-nav-sep"></div>
                <a href="javascript:void(0)" onclick="alibiOpenConsole('/incidents')" class="{cls('console')}">Console</a>
                <a href="/docs" class="{cls('docs')}">API Docs</a>
            </div>
            <div class="alibi-nav-user">
                <span class="alibi-nav-user-name" id="alibi-nav-username"></span>
                <span class="alibi-nav-user-role" id="alibi-nav-role"></span>
                <button class="alibi-nav-logout" onclick="alibiLogout()">Logout</button>
            </div>
        </div>
    </nav>
    <div class="alibi-nav-spacer"></div>
    """


def get_nav_js():
    """JS for the nav bar — user display, console links, logout"""
    return """
    <script>
    (function() {
        // Populate user info
        try {
            const raw = localStorage.getItem('alibi_user');
            if (raw && raw !== 'undefined' && raw !== 'null') {
                const u = JSON.parse(raw);
                const nameEl = document.getElementById('alibi-nav-username');
                const roleEl = document.getElementById('alibi-nav-role');
                if (nameEl) nameEl.textContent = u.full_name || u.username || '';
                if (roleEl) roleEl.textContent = u.role || '';
            }
        } catch(e) {}

        // If no token, redirect to login
        if (!localStorage.getItem('alibi_token') && !window.location.pathname.startsWith('/camera/login')) {
            window.location.href = '/camera/login';
        }
    })();

    function alibiOpenConsole(path) {
        const host = window.location.hostname;
        fetch('http://' + host + ':5173/', { mode: 'no-cors' })
            .then(function() { window.location.href = 'http://' + host + ':5173' + path; })
            .catch(function() { window.location.href = 'http://' + host + ':5174' + path; });
    }

    function alibiLogout() {
        localStorage.removeItem('alibi_token');
        localStorage.removeItem('alibi_user');
        window.location.href = '/camera/login';
    }
    </script>
    """


def build_nav(active_page=""):
    """Returns (css, html, js) tuple for embedding in pages."""
    return get_nav_css(), get_nav_html(active_page), get_nav_js()
