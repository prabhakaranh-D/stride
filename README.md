# Stride – Habit Tracker (Flask + SQLite)

## Run it
    python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
    pip install -r requirements.txt
    python app.py --seed      # optional: demo habits and history
    python app.py             # http://localhost:5000

## Open it on your phone
Phone and computer must be on the same Wi-Fi. Find your computer's IP (e.g. 192.168.1.20)
and open http://192.168.1.20:5000 on the phone.
Service workers need HTTPS on phones (localhost is exempt), so for "Install app"
deploy behind HTTPS (Render, Railway, PythonAnywhere, or `ngrok http 5000` for a quick test).
"Add to Home Screen" works without HTTPS but gives a plain shortcut.

## API
| Method | Path                         | Purpose                                  |
|--------|------------------------------|------------------------------------------|
| GET    | /api/habits                  | List habits                              |
| POST   | /api/habits                  | Create {name, emoji, color, goal}        |
| PUT    | /api/habits/<id>             | Update a habit                           |
| DELETE | /api/habits/<id>             | Delete habit and its history             |
| GET    | /api/logs?days=120           | Completions as {date: [habitIds]}        |
| POST   | /api/habits/<id>/toggle      | Toggle a day {date: "YYYY-MM-DD"}        |
| GET    | /api/stats                   | Streaks and 30-day consistency per habit |

## Files
- app.py – routes, validation, SQLite schema
- static/index.html – the UI (calls the API with fetch)
- static/sw.js, manifest.webmanifest – make it installable and cache the app shell
