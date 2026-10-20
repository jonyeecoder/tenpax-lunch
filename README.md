# Tenpax Lunch

A lunch-ordering app for 10 coworkers: start a lunch run, everyone adds their order, and the organizer sees the total and who has paid. No more scrolling the group chat.

**Live app:** https://jonyeecoder.pythonanywhere.com (joining needs the team code)

**Demo video (48 s):** https://jonyeecoder.github.io/tenpax-lunch/

[![Demo video](docs/poster.jpg)](https://jonyeecoder.github.io/tenpax-lunch/)

Built with Flask + SQLite.

The 4Cs problem statement, success metric and v1 scope are in [PLAN.md](PLAN.md).

## How it works
1. Coworkers join with a shared team code. The team is capped at 10 accounts.
2. Anyone can start a **lunch run** for today: the place and an optional order cutoff time.
3. Everyone adds or edits their order: the item and its price.
4. The organizer sees the full list and total, ticks off who has paid, and closes orders.

## Run it locally
```bash
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env  (then edit the values)
flask run
```
Then open http://127.0.0.1:5000 and join using the `TEAM_CODE` from your `.env`.

The database is a single file, `lunch.db`. It's created on first run and isn't committed.

## Put it online (PythonAnywhere, free)
1. Sign up for a free **Beginner** account at [pythonanywhere.com](https://www.pythonanywhere.com/). Your app will be at `YOUR_USERNAME.pythonanywhere.com`.
2. Open **Consoles → Bash** and run:
   ```bash
   git clone https://github.com/jonyeecoder/tenpax-lunch.git
   cd tenpax-lunch
   bash deploy/setup_pythonanywhere.sh
   ```
   It asks you to choose a team code, then writes `.env` with that code and a random secret key.
3. Go to **Web → Add a new web app → Manual configuration → Python 3.12**.
4. On the Web tab, set **Source code** and **Virtualenv** to the paths the script printed.
5. Click the **WSGI configuration file** link and replace its contents with [`deploy/pythonanywhere_wsgi.py`](deploy/pythonanywhere_wsgi.py), using your username.
6. Turn on **Force HTTPS**, click **Reload**, and open your site.

**Updating later:** push from your computer, then in the PythonAnywhere Bash console run `cd tenpax-lunch && git pull`, and click **Reload** on the Web tab.

Free apps are paused after 3 months unless you log in and click "Run until 3 months from today" on the Web tab.
