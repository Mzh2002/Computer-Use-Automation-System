"""Local-only synthetic back office. No business API is exposed to automation."""

import asyncio
import html
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

SCENARIOS = (
    "normal",
    "slow",
    "transient",
    "permission-denied",
    "session-expired",
    "unexpected-dialog",
    "app-error",
    "ambiguous",
    "wrong-member",
)
MEMBERS = [("10001", "Sample Member A", "1250.50"), ("10002", "Sample Member B", "842.19")]


def db_path() -> Path:
    return Path(os.environ.get("CUA_SANDBOX_DB", ".runtime/mockbank.sqlite3"))


def reset(path: Path | None = None):
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS members (id TEXT PRIMARY KEY, name TEXT, balance TEXT);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            DELETE FROM members; DELETE FROM settings;
        """)
        db.executemany("INSERT INTO members VALUES (?, ?, ?)", MEMBERS)
        db.execute("INSERT INTO settings VALUES ('scenario', 'normal')")


def scenario(name: str, path: Path | None = None):
    if name not in SCENARIOS:
        raise ValueError("Unknown scenario")
    path = path or db_path()
    if not path.exists():
        reset(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT OR REPLACE INTO settings VALUES ('scenario', ?)", (name,))


STYLE = """
body{font:16px system-ui;margin:0;color:#192b3a;background:#f1f5f8}
header{background:#133b50;color:white;padding:22px 32px;display:flex;justify-content:space-between}
header small{color:#bedbe6} main{margin:28px auto;max-width:1000px;padding:0 24px}
h1{font-size:26px}h2{font-size:20px}.card{background:white;border:1px solid #d9e2e9;
border-radius:10px;padding:24px;margin:20px 0}input,button,a.button,select{font:inherit;
padding:10px 14px;border:1px solid #bccbd4;border-radius:5px}button,a.button{
background:#126b76;color:white;cursor:pointer;text-decoration:none;display:inline-block}
label{display:block;margin-bottom:8px}input{margin-right:10px}table{border-collapse:collapse;
width:100%;background:white}td,th{padding:16px;text-align:left;border-bottom:1px solid #d9e2e9}
iframe{width:100%;height:480px;border:1px solid #d9e2e9;background:white;border-radius:10px}
.notice{background:#fff4ce;border-left:4px solid #bd7d16;padding:16px}.muted{color:#506977}
.danger{background:#983832}dialog{border:0;border-radius:12px;max-width:440px;padding:30px}
dialog::backdrop{background:#18313c88}a{color:#096c80}.badge{font-size:12px;border:1px solid;
padding:4px 8px;border-radius:20px}nav{display:flex;gap:20px}.amount{font-size:28px}
"""


def document(body: str, *, frame=False) -> HTMLResponse:
    header = (
        ""
        if frame
        else """<header><div><b>MockBank</b> / Back Office<br>
      <small>Computer-use automation sandbox</small></div><span class="badge">SYNTHETIC DATA</span>
      </header>"""
    )
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
      <meta name="app-version" content="1"><title>MockBank Back Office</title>
      <style>{STYLE}</style></head><body>{header}<main>{body}</main></body></html>""")


def create_app(path: Path | None = None) -> FastAPI:
    path = path or db_path()
    if not path.exists():
        reset(path)
    app = FastAPI(title="MockBank", docs_url=None, redoc_url=None, openapi_url=None)

    def current_scenario():
        with closing(sqlite3.connect(path)) as db, db:
            return db.execute("SELECT value FROM settings WHERE key='scenario'").fetchone()[0]

    def member(member_id: str):
        with closing(sqlite3.connect(path)) as db, db:
            return db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()

    async def interruption(request: Request, member_id: str):
        mode = current_scenario()
        if mode == "slow":
            await asyncio.sleep(0.7)
        if mode == "permission-denied":
            return document("<h2>Permission denied</h2><p>Contact your supervisor.</p>", frame=True)
        if mode == "app-error":
            return document("<h2>Application error</h2><p>Service unavailable.</p>", frame=True)
        if mode == "transient" and request.query_params.get("retry") != "1":
            return document(
                f"""<h2>Temporary service interruption</h2>
                <a class="button" href="/accounts?member_id={quote(member_id)}&retry=1">
                Retry load</a>""",
                frame=True,
            )
        if mode == "session-expired" and request.cookies.get("demo_session") != "restored":
            return document(
                f'''<h2>Session expired</h2><p>A human operator must restore this
                synthetic session.</p><form action="/restore-session" method="post">
                <input type="hidden" name="member_id" value="{html.escape(member_id)}">
                <button>Restore demo session</button></form>''',
                frame=True,
            )
        return None

    @app.get("/", response_class=HTMLResponse)
    def home():
        return document("""<h1>Member servicing</h1><p class="muted">Search a member and review
            their accounts. All records are fictional.</p><section class="card">
            <h2>Find a member</h2><form action="/search" method="get">
            <label for="member-query">Member ID</label>
            <input id="member-query" name="member_id" autocomplete="off" required>
            <button>Search</button></form></section>
            <p>Demo IDs: <code>10001</code>, <code>10002</code>. Unknown ID: <code>99999</code>.</p>
            <p><a href="/lab">Open scenario controls</a></p>""")

    @app.get("/search", response_class=HTMLResponse)
    def search(member_id: str = ""):
        if not (member_id.isascii() and member_id.isdigit() and len(member_id) == 5):
            return document("<h2>Invalid member ID</h2><p>Enter exactly five digits.</p>")
        record = member(member_id)
        if record is None:
            return document("<h2>Member not found</h2><p>No matching record.</p>")
        duplicate = (
            '<a href="/member?member_id=10002">Open member</a>'
            if current_scenario() == "ambiguous"
            else ""
        )
        return document(f"""<h1>Search results</h1><table><tr><th>Member ID</th><th>Name</th>
            <th>Action</th></tr><tr><td data-sensitive>{record[0]}</td>
            <td data-sensitive>{record[1]}</td><td><a href="/member?member_id={record[0]}">
            Open member</a>{duplicate}</td></tr></table>""")

    @app.get("/member", response_class=HTMLResponse)
    def detail(member_id: str):
        record = member(member_id)
        if record is None:
            return document("<h2>Member not found</h2>")
        return document(f"""<h1>Member details</h1><section class="card"><table>
            <tr><th>Member ID</th><td data-sensitive>{record[0]}</td></tr>
            <tr><th>Name</th><td data-sensitive>{record[1]}</td></tr></table>
            <p><a class="button" href="/workspace?member_id={record[0]}">View accounts</a></p>
            </section>""")

    @app.get("/workspace", response_class=HTMLResponse)
    def workspace(member_id: str):
        return document(f"""<h1>Account workspace</h1><p class="muted">Legacy account panel</p>
            <iframe title="Account panel" src="/accounts?member_id={html.escape(member_id)}">
            </iframe>""")

    @app.get("/accounts", response_class=HTMLResponse)
    async def accounts(request: Request, member_id: str):
        interrupted = await interruption(request, member_id)
        if interrupted is not None:
            return interrupted
        return render_accounts(member_id)

    def render_accounts(member_id: str):
        record = member("10001" if current_scenario() == "wrong-member" else member_id)
        if record is None:
            return document("<h2>Member not found</h2>", frame=True)
        dialog = ""
        if current_scenario() == "unexpected-dialog":
            dialog = """<dialog open><h2>Operator review required</h2><p>This unexpected notice
                requires a human to read it.</p><button onclick="this.closest('dialog').remove()">
                Acknowledge notice</button></dialog><script>
                const d=document.querySelector('dialog');d.removeAttribute('open');d.showModal();
                </script>"""
        return document(
            f"""<h2>Account summary</h2><table>
            <tr><th>Member ID</th><td data-sensitive>{record[0]}</td></tr>
            <tr><th>Savings balance</th><td class="amount" data-sensitive>{record[2]}</td></tr>
            <tr><th>Currency</th><td>USD</td></tr></table>
            <p class="muted">Read-only servicing view</p>
            <form action="/close-account" method="post">
            <button class="danger">Close account</button>
            </form>{dialog}""",
            frame=True,
        )

    @app.post("/restore-session")
    async def restore(request: Request):
        from urllib.parse import parse_qs

        params = parse_qs((await request.body()).decode())
        mid = params.get("member_id", ["10001"])[0]
        # Render directly after this human-owned POST; the automation adapter blocks redirects.
        response = render_accounts(mid)
        response.set_cookie("demo_session", "restored", httponly=True, samesite="strict")
        return response

    @app.post("/close-account")
    def close_account():
        return document("<h2>Close account blocked</h2><p>The sandbox never deletes accounts.</p>")

    @app.get("/lab", response_class=HTMLResponse)
    def lab():
        options = "".join(f"<option>{name}</option>" for name in SCENARIOS)
        return document(f"""<h1>Scenario controls</h1><p>Current scenario:
            <b>{current_scenario()}</b></p><form method="post" action="/lab">
            <label for="scenario">Next run scenario</label><select id="scenario" name="scenario">
            {options}</select><button>Apply scenario</button></form>
            <p><a href="/">Return to search</a>
            </p><p class="notice">Open a fresh browser context after changing scenarios.</p>""")

    @app.post("/lab")
    async def update_lab(request: Request):
        from urllib.parse import parse_qs

        params = parse_qs((await request.body()).decode())
        name = params.get("scenario", ["normal"])[0]
        if name not in SCENARIOS:
            return HTMLResponse("Unknown scenario", status_code=400)
        scenario(name, path)
        return RedirectResponse("/lab", status_code=303)

    return app
