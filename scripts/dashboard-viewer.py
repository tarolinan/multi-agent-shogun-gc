#!/usr/bin/env python3
"""
dashboard-viewer.py

Serves dashboard.md as a browser-viewable page with auto-refresh on file change.
Uses only Python3 standard library. No pip install required.

Usage:
    python3 scripts/dashboard-viewer.py
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

PORT = 8787

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    :root {
      --bg: #0d1117;
      --surface: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --heading: #e6edf3;
      --accent: #58a6ff;
      --code-bg: #1c2128;
      --muted: #8b949e;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      height: 100%;
    }
    #app {
      max-width: 900px;
      margin: 0 auto;
      padding: 16px 20px 40px;
    }
    #status-bar {
      position: fixed;
      top: 0; left: 0; right: 0;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 4px 12px;
      font-size: 11px;
      color: var(--muted);
      z-index: 100;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    #status-bar .dot {
      display: inline-block;
      width: 7px; height: 7px;
      border-radius: 50%;
      background: #3fb950;
      margin-right: 5px;
      vertical-align: middle;
    }
    #status-bar .dot.stale { background: #f85149; }
    #content {
      margin-top: 32px;
    }
    /* Markdown styles */
    #content h1, #content h2, #content h3,
    #content h4, #content h5, #content h6 {
      color: var(--heading);
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
      margin: 20px 0 10px;
    }
    #content h1 { font-size: 1.5em; }
    #content h2 { font-size: 1.25em; }
    #content h3 { font-size: 1.1em; border-bottom: none; }
    #content p { margin: 8px 0; }
    #content ul, #content ol {
      margin: 6px 0 6px 20px;
    }
    #content li { margin: 2px 0; }
    #content code {
      background: var(--code-bg);
      padding: 1px 5px;
      border-radius: 4px;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 0.9em;
    }
    #content pre {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
      margin: 10px 0;
    }
    #content pre code {
      background: none;
      padding: 0;
    }
    #content blockquote {
      border-left: 3px solid var(--border);
      padding-left: 12px;
      color: var(--muted);
      margin: 8px 0;
    }
    #content table {
      border-collapse: collapse;
      width: 100%;
      margin: 10px 0;
      font-size: 0.92em;
    }
    #content th, #content td {
      border: 1px solid var(--border);
      padding: 5px 10px;
      text-align: left;
    }
    #content th {
      background: var(--surface);
      color: var(--heading);
    }
    #content a {
      color: var(--accent);
      text-decoration: none;
    }
    #content a:hover { text-decoration: underline; }
    #content hr {
      border: none;
      border-top: 1px solid var(--border);
      margin: 16px 0;
    }
  </style>
</head>
<body>
  <div id="status-bar">
    <span><span class="dot" id="dot"></span><span id="status-text">Connecting...</span></span>
    <span id="last-updated"></span>
  </div>
  <div id="app">
    <div id="content"><em>Loading...</em></div>
  </div>
  <script>
    let lastMtime = null;
    const dot = document.getElementById('dot');
    const statusText = document.getElementById('status-text');
    const lastUpdated = document.getElementById('last-updated');
    const contentEl = document.getElementById('content');

    async function fetchMtime() {
      const res = await fetch('/api/mtime');
      const data = await res.json();
      return data.mtime;
    }

    async function fetchDashboard() {
      const res = await fetch('/api/dashboard');
      return await res.text();
    }

    async function render() {
      const md = await fetchDashboard();
      contentEl.innerHTML = marked.parse(md);
    }

    function setStatus(ok, text) {
      dot.className = 'dot' + (ok ? '' : ' stale');
      statusText.textContent = text;
    }

    async function poll() {
      try {
        const mtime = await fetchMtime();
        if (mtime !== lastMtime) {
          lastMtime = mtime;
          await render();
          const d = new Date();
          lastUpdated.textContent = 'Updated ' + d.toLocaleTimeString('ja-JP');
        }
        setStatus(true, 'Live');
      } catch (e) {
        setStatus(false, 'Connection error');
      }
    }

    poll();
    setInterval(poll, 1500);
  </script>
</body>
</html>
"""


def get_repo_root() -> Path:
    """Resolve the git repository root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        # Fall back to the directory containing this script's parent
        return Path(__file__).resolve().parent.parent


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    dashboard_path: Path  # set before server starts

    def log_message(self, fmt, *args):
        # Suppress default access log to keep terminal clean
        pass

    def do_GET(self):
        if self.path == "/":
            self._serve_html()
        elif self.path == "/api/dashboard":
            self._serve_markdown()
        elif self.path == "/api/mtime":
            self._serve_mtime()
        else:
            self.send_error(404)

    def _serve_html(self):
        body = HTML_TEMPLATE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_markdown(self):
        try:
            text = self.dashboard_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.send_error(404, "dashboard.md not found")
            return
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mtime(self):
        try:
            mtime = self.dashboard_path.stat().st_mtime
        except FileNotFoundError:
            self.send_error(404, "dashboard.md not found")
            return
        body = json.dumps({"mtime": mtime}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    repo_root = get_repo_root()
    dashboard_path = repo_root / "dashboard.md"

    if not dashboard_path.exists():
        print(f"Error: dashboard.md not found at {dashboard_path}", file=sys.stderr)
        sys.exit(1)

    # Inject path into handler class
    DashboardHandler.dashboard_path = dashboard_path

    import socket

    try:
        server = http.server.HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    except OSError as e:
        if e.errno == 48 or e.errno == 98:  # Address already in use (macOS=48, Linux=98)
            print(
                f"Error: Port {PORT} is already in use. "
                "Another instance may be running.",
                file=sys.stderr,
            )
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    url = f"http://127.0.0.1:{PORT}"
    print(f"Dashboard viewer running at {url}")
    print(f"Serving: {dashboard_path}")
    print("Press Ctrl+C to stop.")

    # Open browser after a short delay so the server is ready
    def open_browser():
        import time
        time.sleep(0.3)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
