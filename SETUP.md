# Running this project on another computer (HP Victus Gaming 15 / Windows 11)

This is a plain web project — **no GPU, no cloud accounts, no API keys needed**. The
Victus is far more than enough. It runs two local processes: a Python API (port
**8137**) and a Next.js web app (port **3000**), talking to a local SQLite file.

> The HP Victus 15 ships with **Windows 11**, so the commands below are **Windows-first
> (PowerShell)**. macOS/Linux equivalents are in [§7](#7-macoslinux-equivalents).

---

## 0. TL;DR (once the tools in §1 are installed)

Open **two** terminals in the project folder.

**Terminal 1 — backend**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --port 8137
```

**Terminal 2 — frontend**
```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**, sign in with any email (no password), add a few
stocks (try `RELIANCE`, `ZOMATO`, `HDFCBANK`). Done.

---

## 1. Install the prerequisites (one-time)

You need **Python** and **Node.js**. Two easy ways:

### Option A — Windows Package Manager (fastest)
Open **PowerShell** and run:
```powershell
winget install -e --id Python.Python.3.12
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Git.Git      # optional, only if you'll clone from GitHub
```
Then **close and reopen** PowerShell so the new tools are on your PATH.

### Option B — download installers
- **Python 3.12** (or 3.11/3.13): https://www.python.org/downloads/windows/ — during install, **tick "Add python.exe to PATH."**
- **Node.js 20 LTS** (18.18+ required): https://nodejs.org/en/download

### Verify
```powershell
python --version    # 3.11, 3.12, or 3.13   (avoid 3.14 — some libraries lack wheels)
node --version      # v18.18+  (v20 LTS recommended)
npm --version
```
If `python` isn't found, try `py --version`, or reinstall with "Add to PATH" ticked.

---

## 2. Get the project onto the laptop

Pick whichever is convenient:

- **USB / cloud drive (simplest):** copy the whole `groww-code-watchlist` folder over.
  Before copying, delete the machine-specific build folders so they get rebuilt cleanly
  on the new PC (they're large and won't work across machines anyway):
  `backend\.venv`, `frontend\node_modules`, `frontend\.next`, and any `*.db` files.
  *(If you use the ZIP I can generate for you, these are already excluded.)*

- **Git (if it's in a repo):**
  ```powershell
  git clone <your-repo-url> groww-code-watchlist
  ```

Then `cd` into the folder:
```powershell
cd path\to\groww-code-watchlist
```

---

## 3. Start the backend (Terminal 1)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --port 8137
```

You should see `Uvicorn running on http://127.0.0.1:8137`. Leave this window open.

- Check it: open **http://localhost:8137/docs** (interactive API) or
  **http://localhost:8137/api/health** (should say `"status": "ok"`).
- On first run Windows may pop a **Firewall** dialog — allow access on private networks.

> **Why `.\.venv\Scripts\python -m ...`?** Calling the venv's Python directly avoids the
> PowerShell "activate" script, which can be blocked by execution policy. If you prefer
> to activate: `.\.venv\Scripts\Activate.ps1` (see [§6](#6-troubleshooting) if it errors),
> then you can just type `uvicorn app.main:app --port 8137`.

---

## 4. Start the frontend (Terminal 2)

Open a **second** PowerShell window in the project folder:
```powershell
cd frontend
npm install          # first time only; downloads dependencies
npm run dev
```

When it prints `Local: http://localhost:3000`, open that in your browser.

- Sign in with any email (e.g. `you@example.com`) — it's passwordless, for the demo.
- Add stocks from the search box; watch prices update live; leave and come back to
  see the "while you were away" summary.
- Prices are **simulated** (clearly labelled) — that's intentional; see the README.

The frontend talks to the backend at `http://localhost:8137` by default, so as long as
both are running on the same laptop, nothing else to configure.

---

## 5. Optional extras

**Run the tests** (proves the backend logic on the new machine):
```powershell
cd backend
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```
Expect `42 passed`.

**Production build of the frontend** (faster than dev mode):
```powershell
cd frontend
npm run build
npm run start        # serves on http://localhost:3000
```

**Change ports / secret** (only if you need to): set environment variables before
starting the backend, e.g. in PowerShell:
```powershell
$env:JWT_SECRET = "some-long-random-string"   # recommended if others will use it
.\.venv\Scripts\python -m uvicorn app.main:app --port 8137
```
If you run the frontend on a different port, tell the backend which origin to allow:
`$env:CORS_ORIGINS = "http://localhost:3001"`.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `python` / `py` not recognised | Reinstall Python with **"Add to PATH"** ticked, then reopen the terminal. Try `py -3.12` instead of `python`. |
| `Activate.ps1 cannot be loaded ... execution policy` | Either use the direct form `.\.venv\Scripts\python -m ...` (as above), **or** run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` and re-activate. |
| `Port 8137 (or 3000) is already in use` | Close the other process, or run on another port: backend `--port 8138`; frontend `npm run dev -- -p 3001` (then set `CORS_ORIGINS` as in §5). |
| Frontend loads but says it can't reach the backend / "Is the backend running?" | Make sure Terminal 1 (uvicorn) is still running and `http://localhost:8137/api/health` works. |
| `npm install` fails or is very slow | Ensure Node **18.18+** (`node --version`). Delete `frontend\node_modules` and `package-lock.json` isn't required — just retry. On a corporate network, a proxy may block npm. |
| `pip install` fails building a package | You're likely on **Python 3.14**; install 3.12 or 3.13 instead (they have prebuilt wheels). |
| Browser shows old data after restarting the backend | The backend uses a local SQLite file (`backend\watchlist.db`). Delete it to start fresh; sign in again. |
| Antivirus / SmartScreen warning on first Node run | Allow it — it's your local dev server, not a downloaded executable. |

---

## 7. macOS / Linux equivalents

Same steps; only the venv path differs.

```bash
# backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8137
```
```bash
# frontend (second terminal)
cd frontend
npm install
npm run dev
```

---

## 8. What's running (mental model)

```
Browser  →  http://localhost:3000   (Next.js frontend, "npm run dev")
                     │  REST + Server-Sent Events
                     ▼
             http://localhost:8137   (FastAPI backend, "uvicorn")
                     │
                     ▼
             backend/watchlist.db    (SQLite — created automatically)
```

Two terminals, two ports, one local database file. No internet required after the
one-time `pip install` / `npm install`.
