import csv
import hashlib
import hmac
import html as _html
import io
import json
import os
import secrets

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from . import db

router = APIRouter(prefix="/admin")
COOKIE_NAME = "roman_admin"
_STATUS_OPTS = ("open", "confirmed", "resolved", "spam")
_STATUS_COLORS = {
    "open": "#6c757d", "confirmed": "#856404",
    "resolved": "#155724", "spam": "#721c24",
}


def _e(v) -> str:
    """HTML-escape a value for safe inline rendering."""
    return _html.escape(str(v or ""))


# ── Session helpers ───────────────────────────────────────────────────────────

_BOOT_NONCE = secrets.token_hex(8)

def _session_token() -> str:
    raw = os.environ.get("ADMIN_TOKEN", "")
    return hmac.new(
        raw.encode(),
        f"roman-names-admin:{_BOOT_NONCE}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _check(session: str | None) -> bool:
    raw = os.environ.get("ADMIN_TOKEN", "")
    if not raw or not session:
        return False
    return secrets.compare_digest(session, _session_token())


def _require(session: str | None) -> None:
    if not _check(session):
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})


# ── HTML shell ────────────────────────────────────────────────────────────────

def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Admin — {title}</title>
<style>
body{{font-family:-apple-system,sans-serif;margin:0;background:#f8f9fa;color:#2c3e50}}
nav{{background:#2c3e50;padding:10px 20px;display:flex;gap:20px;align-items:center}}
nav a{{color:#adb5bd;text-decoration:none;font-size:.9rem}}nav a:hover{{color:#fff}}
nav strong{{color:#fff;margin-right:20px}}
main{{padding:20px;max-width:1200px;margin:0 auto}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:6px;overflow:hidden;
       box-shadow:0 1px 4px rgba(0,0,0,.1);margin-bottom:20px}}
th{{background:#f0f0f0;text-align:left;padding:8px 12px;font-size:.82rem}}
td{{padding:8px 12px;border-top:1px solid #eee;font-size:.85rem;vertical-align:top}}
.btn{{padding:4px 10px;border-radius:4px;border:none;cursor:pointer;font-size:.82rem;
      text-decoration:none;display:inline-block}}
.btn-primary{{background:#c0392b;color:#fff}}.btn-secondary{{background:#6c757d;color:#fff}}
.btn-sm{{padding:2px 8px;font-size:.78rem}}
form.inline{{display:inline}}
input,textarea,select{{width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;
                       font-size:.88rem;box-sizing:border-box}}
textarea{{font-family:monospace;font-size:.82rem;resize:vertical}}
.card{{background:#fff;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.1);
       padding:20px;margin-bottom:20px}}
h1{{font-size:1.3rem;margin:0 0 16px}}
.flash-ok{{background:#d4edda;color:#155724;padding:10px 16px;border-radius:4px;
           margin-bottom:16px;font-size:.88rem}}
.flash-err{{background:#f8d7da;color:#721c24;padding:10px 16px;border-radius:4px;
            margin-bottom:16px;font-size:.88rem}}
.toolbar{{display:flex;gap:8px;margin-bottom:16px;align-items:center}}
.sel-inline{{width:auto;padding:2px 6px}}
</style>
</head>
<body>
<nav>
  <strong>Roman Names Admin</strong>
  <a href="/admin/flags">Flags</a>
  <a href="/admin/inscription">Inscriptions</a>
  <a href="/admin/edit-log">Edit Log</a>
  <a href="/admin/logout">Logout</a>
</nav>
<main>{content}</main>
</body>
</html>""", headers={"Cache-Control": "no-store"})


# ── Login / logout ────────────────────────────────────────────────────────────

def _login_form(error: str = "") -> str:
    err_html = f'<div class="flash-err">{_e(error)}</div>' if error else ""
    return f"""
<div class="card" style="max-width:360px;margin:60px auto">
  <h1>Login</h1>
  {err_html}
  <form method="post" action="/admin/login">
    <div style="margin-bottom:12px">
      <label style="display:block;font-size:.85rem;margin-bottom:4px">Admin token</label>
      <input type="password" name="token" autofocus required>
    </div>
    <button class="btn btn-primary" type="submit">Sign in</button>
  </form>
</div>"""


@router.get("/login", response_class=HTMLResponse)
def login_get():
    return _page("Login", _login_form())


@router.post("/login")
def login_post(token: str = Form(...)):
    raw = os.environ.get("ADMIN_TOKEN", "")
    if not raw or not secrets.compare_digest(token, raw):
        return _page("Login", _login_form("Invalid token."))
    resp = RedirectResponse("/admin/flags", status_code=303)
    resp.set_cookie(COOKIE_NAME, _session_token(), httponly=True, samesite="lax")
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ── Flags ─────────────────────────────────────────────────────────────────────

@router.get("/flags/export")
def flags_export(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["id", "edcs_id", "category", "comment", "email",
                    "created_at", "status", "resolved_at"],
    )
    writer.writeheader()
    writer.writerows(db.get_flags())
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flags.csv"},
    )


@router.get("/flags", response_class=HTMLResponse)
def flags_list(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    flags = db.get_flags()
    rows = ""
    for f in flags:
        color = _STATUS_COLORS.get(f["status"], "#000")
        opts = "".join(
            f'<option value="{_e(s)}"{" selected" if s == f["status"] else ""}>{_e(s)}</option>'
            for s in _STATUS_OPTS
        )
        rows += f"""<tr>
  <td><a href="/admin/inscription/{_e(f['edcs_id'])}">{_e(f['edcs_id'])}</a></td>
  <td>{_e(f['category'])}</td>
  <td style="max-width:260px">{_e(f.get('comment') or '')}</td>
  <td>{_e(f.get('email') or '')}</td>
  <td>{_e(f['created_at'][:10])}</td>
  <td style="color:{color};font-weight:600">{_e(f['status'])}</td>
  <td>
    <form class="inline" method="post" action="/admin/flags/{f['id']}/status">
      <select class="sel-inline" name="status">{opts}</select>
      <button class="btn btn-sm btn-secondary" type="submit">Set</button>
    </form>
    <a class="btn btn-sm" href="/#edcs_id={_e(f['edcs_id'])}" target="_blank">View</a>
  </td>
</tr>"""
    content = f"""
<div class="toolbar">
  <h1 style="margin:0;flex:1">Flags ({len(flags)})</h1>
  <a class="btn btn-secondary" href="/admin/flags/export">Download CSV</a>
</div>
<table>
  <thead><tr>
    <th>EDCS ID</th><th>Category</th><th>Comment</th><th>Email</th>
    <th>Date</th><th>Status</th><th>Actions</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    return _page("Flags", content)


@router.post("/flags/{flag_id}/status")
def flag_set_status(
    flag_id: int,
    status: str = Form(...),
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    if status not in _STATUS_OPTS:
        raise HTTPException(400, "Invalid status")
    db.update_flag_status(flag_id, status)
    return RedirectResponse("/admin/flags", status_code=303)


# ── Inscription edit ──────────────────────────────────────────────────────────

@router.get("/inscription", response_class=HTMLResponse)
def inscription_search(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    return _page("Edit Inscription", """
<div class="card" style="max-width:480px">
  <h1>Edit Inscription</h1>
  <form method="get" action="/admin/inscription/search">
    <div style="display:flex;gap:8px">
      <input name="q" placeholder="EDCS-12345678" style="flex:1">
      <button class="btn btn-primary" type="submit">Load</button>
    </div>
  </form>
</div>""")


@router.get("/inscription/search")
def inscription_search_redirect(
    q: str = "",
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    edcs_id = q.strip().upper()
    if not edcs_id:
        return RedirectResponse("/admin/inscription", status_code=303)
    return RedirectResponse(f"/admin/inscription/{edcs_id}", status_code=303)


@router.get("/inscription/{edcs_id}", response_class=HTMLResponse)
def inscription_edit_get(
    edcs_id: str,
    saved: str = "",
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    insc = db.get_inscription_for_edit(edcs_id)
    if insc is None:
        return _page("Not Found", f'<div class="flash-err">Inscription {_e(edcs_id)} not found.</div>')

    persons_raw = insc["overrides"] or insc["persons"] or "[]"
    try:
        persons_display = json.dumps(json.loads(persons_raw), indent=2)
    except Exception:
        persons_display = persons_raw

    flash = '<div class="flash-ok">Saved successfully.</div>' if saved == "1" else ""
    raw_block = ""
    if insc.get("raw_text"):
        raw_block = (
            "<details style='margin-bottom:16px'>"
            "<summary style='cursor:pointer;font-size:.82rem;color:#6c757d'>Raw inscription text</summary>"
            f"<pre style='font-size:.78rem;background:#f8f9fa;padding:10px;border-radius:4px;"
            f"white-space:pre-wrap'>{_e(insc['raw_text'])}</pre></details>"
        )

    content = f"""{flash}
<div class="card">
  <h1>Edit: {_e(edcs_id)}</h1>
  <p style="color:#6c757d;font-size:.85rem;margin-bottom:12px">{_e(insc.get('findspot') or '')}</p>
  {raw_block}
  <form method="post" action="/admin/inscription/{_e(edcs_id)}/edit">
    <div style="margin-bottom:16px">
      <label style="font-weight:600;font-size:.85rem;display:block;margin-bottom:4px">
        Persons JSON (saved to overrides column)
      </label>
      <textarea name="persons" rows="10">{_e(persons_display)}</textarea>
    </div>
    <div style="margin-bottom:16px">
      <label style="font-weight:600;font-size:.85rem;display:block;margin-bottom:4px">Translation</label>
      <textarea name="translation" rows="4">{_e(insc.get('translation') or '')}</textarea>
    </div>
    <div style="margin-bottom:16px">
      <label style="font-weight:600;font-size:.85rem;display:block;margin-bottom:4px">Summary</label>
      <textarea name="summary" rows="3">{_e(insc.get('summary') or '')}</textarea>
    </div>
    <button class="btn btn-primary" type="submit">Save changes</button>
    <a class="btn btn-secondary" href="/#edcs_id={_e(edcs_id)}" target="_blank"
       style="margin-left:8px">View on map ↗</a>
  </form>
</div>"""
    return _page(f"Edit {_e(edcs_id)}", content)


@router.post("/inscription/{edcs_id}/edit")
def inscription_edit_post(
    edcs_id: str,
    persons: str = Form(""),
    translation: str = Form(""),
    summary: str = Form(""),
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    _require(session)
    insc = db.get_inscription_for_edit(edcs_id)
    if insc is None:
        raise HTTPException(404)

    try:
        json.loads(persons)
    except json.JSONDecodeError:
        return _page(
            "Edit Error",
            f'<div class="flash-err">Invalid JSON in persons field.</div>'
            f'<a href="/admin/inscription/{_e(edcs_id)}">← Back</a>',
        )

    # Only log fields that actually changed
    current_persons = insc["overrides"] or insc["persons"] or "[]"
    if persons != current_persons:
        db.save_edit(edcs_id, "persons", persons or None)
    if translation != (insc.get("translation") or ""):
        db.save_edit(edcs_id, "translation", translation or None)
    if summary != (insc.get("summary") or ""):
        db.save_edit(edcs_id, "summary", summary or None)

    return RedirectResponse(f"/admin/inscription/{edcs_id}?saved=1", status_code=303)


# ── Edit log ──────────────────────────────────────────────────────────────────

@router.get("/edit-log/export")
def edit_log_export(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["id", "edcs_id", "field", "old_value", "new_value",
                    "edited_at", "applied_at"],
    )
    writer.writeheader()
    writer.writerows(db.get_edit_log())
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=edit_log.csv"},
    )


@router.get("/edit-log", response_class=HTMLResponse)
def edit_log_list(session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    _require(session)
    rows_data = db.get_edit_log()
    rows = ""
    for r in rows_data:
        applied = r.get("applied_at") or ""
        rows += f"""<tr>
  <td><a href="/admin/inscription/{_e(r['edcs_id'])}">{_e(r['edcs_id'])}</a></td>
  <td>{_e(r['field'])}</td>
  <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
      title="{_e((r.get('old_value') or '')[:60])}">{_e((r.get('old_value') or '')[:60])}</td>
  <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
      title="{_e((r.get('new_value') or '')[:60])}">{_e((r.get('new_value') or '')[:60])}</td>
  <td>{_e(r['edited_at'][:16])}</td>
  <td>{"✓ " + _e(applied[:10]) if applied else "—"}</td>
</tr>"""
    content = f"""
<div class="toolbar">
  <h1 style="margin:0;flex:1">Edit Log ({len(rows_data)} entries)</h1>
  <a class="btn btn-secondary" href="/admin/edit-log/export">Download CSV</a>
</div>
<table>
  <thead><tr>
    <th>EDCS ID</th><th>Field</th><th>Old Value</th><th>New Value</th>
    <th>Edited At</th><th>Applied</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    return _page("Edit Log", content)
