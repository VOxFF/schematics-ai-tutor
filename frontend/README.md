# Frontend

React app for the grid editor and tutor UI, built with Vite. See [docs/gui.md](../docs/gui.md) and [docs/design.md](../docs/design.md).

## Run

From the repo root, `./start.sh` installs dependencies when needed and starts the dev server on http://127.0.0.1:5173 (`FRONTEND_PORT` to change). The dev server forwards `/api` and `/ws` to the backend, so the browser talks to one origin.

## Develop

```sh
cd frontend
npm test          # Vitest
npm run build     # production build into dist/
```
