# -*- coding: utf-8 -*-
"""Optional: serve the generated outputs on http://localhost:8000 (stdlib only).

    python run_local.py --mode demo && python app.py
"""
import functools
import http.server
import os
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs")
PORT = int(os.environ.get("PORT", "8000"))
DASH = "SPX_Voice_of_Operations_Dashboard.html"

if __name__ == "__main__":
    if not os.path.exists(os.path.join(OUT, DASH)):
        raise SystemExit("No dashboard yet — run: python run_local.py --mode demo")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=OUT)
    url = f"http://localhost:{PORT}/{DASH}"
    print(f"Serving {OUT} at {url}  (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()
