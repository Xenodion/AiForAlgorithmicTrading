# React App Startup

The app runs as two processes:

1. Python API on `http://localhost:8000`
2. React/Vite frontend on `http://localhost:5173`

## 1. Start IBKR Gateway

Start Client Portal Gateway and log in first, as usual:

```bash
cd ~/Desktop/clientportal.gw
./bin/run.sh root/conf.yaml
```

Open `https://localhost:5050`, accept the local certificate warning, and log in.

## 2. Start The API

From the project root:

```bash
python3 -m pip install -r requirements.txt
uvicorn src.api.server:app --reload --port 8000
```

Quick health check:

```bash
curl http://localhost:8000/api/status
```

## 3. Start React

From the `frontend` folder:

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

## Notes

- `frontend/package-lock.json` pins the installed React/Vite dependencies.
- `frontend/node_modules` and `frontend/dist` are intentionally ignored.
- Set `VITE_API_BASE=http://localhost:8000` only if you need a non-default API URL.
- The Orders tab is still a preview; routing is intentionally disabled.
