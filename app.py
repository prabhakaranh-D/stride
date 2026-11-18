"""Stride habit tracker backend: Flask + SQLite (single user)."""
import os
import random
import sqlite3
import sys
import uuid
from datetime import date, timedelta

from flask import Flask, abort, g, jsonify, request, send_from_directory

DB_PATH = "habits.db"
app = Flask(__name__, static_folder="static", static_url_path="/static")

SCHEMA = """
CREATE TABLE IF NOT EXISTS habits (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    emoji      TEXT NOT NULL,
    color      TEXT NOT NULL,
    goal       INTEGER NOT NULL DEFAULT 5,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS logs (
    habit_id TEXT NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    day      TEXT NOT NULL,              -- YYYY-MM-DD
    PRIMARY KEY (habit_id, day)
);
"""


# ---------- database helpers ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)


def habit_dict(row):
    return {k: row[k] for k in ("id", "name", "emoji", "color", "goal")}


def clean_habit(data):
    """Validate and normalise incoming habit JSON."""
    data = data or {}
    name = str(data.get("name", "")).strip()[:40]
    if not name:
        abort(400, "Habit name is required.")
    try:
        goal = int(data.get("goal", 5))
    except (TypeError, ValueError):
        abort(400, "Goal must be a number.")
    return {
        "name": name,
        "emoji": str(data.get("emoji", "🏃"))[:8],
        "color": str(data.get("color", "#fc4c02"))[:9],
        "goal": min(7, max(1, goal)),
    }


def parse_day(value):
    try:
        return date.fromisoformat(value).isoformat() if value else date.today().isoformat()
    except ValueError:
        abort(400, "Date must be YYYY-MM-DD.")


@app.errorhandler(400)
def bad_request(err):
    return jsonify(error=err.description), 400


@app.errorhandler(404)
def not_found(err):
    return jsonify(error="Not found."), 404


# ---------- API ----------
@app.get("/api/habits")
def list_habits():
    rows = db().execute("SELECT * FROM habits ORDER BY created_at, rowid").fetchall()
    return jsonify([habit_dict(r) for r in rows])


@app.post("/api/habits")
def create_habit():
    h = clean_habit(request.get_json(silent=True))
    hid = uuid.uuid4().hex[:12]
    db().execute(
        "INSERT INTO habits (id, name, emoji, color, goal) VALUES (?, ?, ?, ?, ?)",
        (hid, h["name"], h["emoji"], h["color"], h["goal"]),
    )
    db().commit()
    return jsonify({"id": hid, **h}), 201


@app.put("/api/habits/<hid>")
def update_habit(hid):
    h = clean_habit(request.get_json(silent=True))
    cur = db().execute(
        "UPDATE habits SET name=?, emoji=?, color=?, goal=? WHERE id=?",
        (h["name"], h["emoji"], h["color"], h["goal"], hid),
    )
    db().commit()
    if cur.rowcount == 0:
        abort(404)
    return jsonify({"id": hid, **h})


@app.delete("/api/habits/<hid>")
def delete_habit(hid):
    cur = db().execute("DELETE FROM habits WHERE id=?", (hid,))
    db().commit()
    if cur.rowcount == 0:
        abort(404)
    return "", 204


@app.get("/api/logs")
def get_logs():
    """Returns {"2026-11-18": ["habitId", ...]} for the last N days."""
    days = min(730, max(1, request.args.get("days", 365, type=int)))
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = db().execute("SELECT habit_id, day FROM logs WHERE day >= ?", (since,)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["day"], []).append(r["habit_id"])
    return jsonify(out)


@app.get("/api/export")
def export_data():
    """Export all habits, logs, and calculated stats as JSON download."""
    habits = [dict(r) for r in db().execute("SELECT * FROM habits ORDER BY created_at").fetchall()]
    logs = [dict(r) for r in db().execute("SELECT habit_id, day FROM logs ORDER BY day DESC").fetchall()]
    return jsonify({
        "exported_at": date.today().isoformat(),
        "total_habits": len(habits),
        "total_checkins": len(logs),
        "habits": habits,
        "logs": logs
    })


@app.post("/api/habits/<hid>/toggle")
def toggle(hid):
    if not db().execute("SELECT 1 FROM habits WHERE id=?", (hid,)).fetchone():
        abort(404)
    day = parse_day((request.get_json(silent=True) or {}).get("date"))
    deleted = db().execute("DELETE FROM logs WHERE habit_id=? AND day=?", (hid, day)).rowcount
    if not deleted:
        db().execute("INSERT INTO logs (habit_id, day) VALUES (?, ?)", (hid, day))
    db().commit()
    return jsonify(habit_id=hid, date=day, done=not deleted)


@app.get("/api/stats")
def stats():
    """Per-habit current streak, best streak and 30-day consistency."""
    today = date.today()
    result = []
    for h in db().execute("SELECT * FROM habits ORDER BY created_at, rowid").fetchall():
        days = {r["day"] for r in db().execute("SELECT day FROM logs WHERE habit_id=?", (h["id"],))}
        # current streak (today may still be pending)
        cursor = today if today.isoformat() in days else today - timedelta(days=1)
        current = 0
        while cursor.isoformat() in days:
            current += 1
            cursor -= timedelta(days=1)
        # best streak
        best = run = 0
        for i in range(365, -1, -1):
            if (today - timedelta(days=i)).isoformat() in days:
                run += 1
                best = max(best, run)
            else:
                run = 0
        last30 = sum((today - timedelta(days=i)).isoformat() in days for i in range(30))
        result.append({**habit_dict(h), "current_streak": current, "best_streak": best,
                       "consistency_30d": round(last30 / 30 * 100)})
    return jsonify(result)


# ---------- PWA / front end ----------
@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/sw.js")  # served from root so the worker controls the whole app
def service_worker():
    resp = send_from_directory("static", "sw.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/share-target")
def share_target():
    """Handle PWA share target — redirect to home with shared text as a new habit name hint."""
    title = request.args.get("title", "") or request.args.get("text", "")
    if title:
        return send_from_directory("static", "index.html")
    return send_from_directory("static", "index.html")


@app.get("/.well-known/assetlinks.json")
def assetlinks():
    """Serve Digital Asset Links for Android Trusted Web Activity (TWA)."""
    well_known_dir = os.path.join(app.root_path, "static", ".well-known")
    if os.path.exists(os.path.join(well_known_dir, "assetlinks.json")):
        return send_from_directory(well_known_dir, "assetlinks.json", mimetype="application/json")
    return jsonify([{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": "com.onrender.stride_2_83gv.twa",
            "sha256_cert_fingerprints": [
                "58:70:CD:88:97:CE:A9:21:12:30:DA:43:66:7D:35:9C:EF:9A:26:AD:5B:D9:D9:64:93:1B:39:78:AD:67:8C:22"
            ]
        }
    }])


# ---------- demo data ----------
def seed():
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        if conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]:
            print("Database already has habits; skipping seed.")
            return
        sample = [("Morning run", "🏃", "#fc4c02", 4, .55), ("Drink 2L water", "💧", "#1e88e5", 7, .8),
                  ("Read 20 pages", "📖", "#2e9e5b", 5, .6)]
        for name, emoji, color, goal, p in sample:
            hid = uuid.uuid4().hex[:12]
            conn.execute("INSERT INTO habits (id,name,emoji,color,goal) VALUES (?,?,?,?,?)",
                         (hid, name, emoji, color, goal))
            for i in range(1, 60):
                if random.random() < p:
                    conn.execute("INSERT INTO logs VALUES (?,?)",
                                 (hid, (date.today() - timedelta(days=i)).isoformat()))
    print("Seeded sample habits.")


init_db()

if __name__ == "__main__":
    if "--seed" in sys.argv:
        seed()
    else:
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=False)
