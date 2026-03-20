"""
Mobile Home Page - Main entry point for iPhone/mobile access
Provides access to all Alibi features from a single mobile-friendly page
"""
from alibi.alibi_nav import build_nav

_nav_css, _nav_html, _nav_js = build_nav(active_page="home")

MOBILE_HOME_HTML = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>Alibi</title>
    <style>
        {_nav_css}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1117;
            min-height: 100vh;
            color: #e5e7eb;
        }}

        .container {{
            max-width: 720px;
            margin: 0 auto;
            padding: 24px 16px 40px;
        }}

        .page-title {{
            font-size: 22px;
            font-weight: 700;
            color: #fff;
            margin-bottom: 24px;
        }}

        .section-title {{
            color: rgba(255,255,255,0.45);
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin: 28px 0 12px 0;
        }}

        .card-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
        }}

        @media (min-width: 500px) {{
            .card-grid {{ grid-template-columns: 1fr 1fr; }}
        }}

        .card {{
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 18px 20px;
            text-decoration: none;
            color: inherit;
            display: flex;
            align-items: center;
            gap: 16px;
            transition: all 0.15s ease;
        }}

        .card:hover {{
            background: rgba(255,255,255,0.07);
            border-color: rgba(99, 102, 241, 0.25);
        }}

        .card:active {{
            transform: scale(0.98);
        }}

        .card-icon {{
            font-size: 24px;
            width: 44px;
            height: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(99, 102, 241, 0.12);
            border-radius: 10px;
            flex-shrink: 0;
        }}

        .card-content {{
            flex: 1;
            min-width: 0;
        }}

        .card-title {{
            font-size: 15px;
            font-weight: 600;
            color: #f3f4f6;
            margin-bottom: 2px;
        }}

        .card-description {{
            font-size: 12px;
            color: rgba(255,255,255,0.4);
            line-height: 1.4;
        }}

        .featured {{
            background: rgba(99, 102, 241, 0.12);
            border-color: rgba(99, 102, 241, 0.2);
        }}

        .featured:hover {{
            background: rgba(99, 102, 241, 0.18);
            border-color: rgba(99, 102, 241, 0.35);
        }}

        .featured .card-icon {{
            background: rgba(99, 102, 241, 0.25);
        }}

        .footer {{
            text-align: center;
            color: rgba(255,255,255,0.2);
            padding: 40px 0 20px;
            font-size: 11px;
        }}
    </style>
</head>
<body>
    {_nav_html}

    <div class="container">
        <div class="page-title">Dashboard</div>

        <div class="card-grid">
            <a href="/camera/secure-stream" class="card featured" style="grid-column: 1 / -1;">
                <div class="card-icon">&#128274;</div>
                <div class="card-content">
                    <div class="card-title">Security Camera</div>
                    <div class="card-description">Live feed with AI threat detection, plate & face recognition</div>
                </div>
            </a>
        </div>

        <div class="section-title">Operations</div>

        <div class="card-grid">
            <a href="javascript:void(0)" onclick="alibiOpenConsole('/')" class="card">
                <div class="card-icon">&#128202;</div>
                <div class="card-content">
                    <div class="card-title">Control Room</div>
                    <div class="card-description">Incidents, cameras, metrics, reports</div>
                </div>
            </a>

            <a href="/camera/history" class="card">
                <div class="card-icon">&#128247;</div>
                <div class="card-content">
                    <div class="card-title">Camera History</div>
                    <div class="card-description">Snapshots and AI descriptions</div>
                </div>
            </a>

            <a href="/camera/insights" class="card">
                <div class="card-icon">&#129504;</div>
                <div class="card-content">
                    <div class="card-title">Insights</div>
                    <div class="card-description">AI-powered analysis and patterns</div>
                </div>
            </a>

            <a href="javascript:void(0)" onclick="alibiOpenConsole('/watchlist')" class="card">
                <div class="card-icon">&#128100;</div>
                <div class="card-content">
                    <div class="card-title">Watchlist</div>
                    <div class="card-description">Face recognition management</div>
                </div>
            </a>

            <a href="javascript:void(0)" onclick="alibiOpenConsole('/vehicle-search')" class="card">
                <div class="card-icon">&#128663;</div>
                <div class="card-content">
                    <div class="card-title">Vehicle Search</div>
                    <div class="card-description">Plate sightings and hotlist</div>
                </div>
            </a>

            <a href="/camera/training" class="card">
                <div class="card-icon">&#127891;</div>
                <div class="card-content">
                    <div class="card-title">Training</div>
                    <div class="card-description">Improve AI vision accuracy</div>
                </div>
            </a>
        </div>

        <div class="section-title">Administration</div>

        <div class="card-grid">
            <a href="/docs" class="card">
                <div class="card-icon">&#128218;</div>
                <div class="card-content">
                    <div class="card-title">API Documentation</div>
                    <div class="card-description">Interactive API testing</div>
                </div>
            </a>

            <a href="javascript:void(0)" onclick="alibiOpenConsole('/settings')" class="card">
                <div class="card-icon">&#9881;</div>
                <div class="card-content">
                    <div class="card-title">Settings</div>
                    <div class="card-description">System configuration (admin)</div>
                </div>
            </a>
        </div>

        <div class="footer">
            Alibi Police Oversight System &middot; Namibia 2026
        </div>
    </div>

    {_nav_js}
</body>
</html>
"""
