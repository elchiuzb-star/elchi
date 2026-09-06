# Working on Elchi

Two people work in this repo at once — one on the API, one on the apps. The rules
below exist so those two streams never land on top of each other.

## One-time setup

```bash
git config core.hooksPath .githooks
```

That switches on `.githooks/pre-push`, which refuses a direct push to `main`.
Run it once per clone. Nothing else in the repo depends on it.

## Who owns what

The repo is one tree with four independent surfaces. Stay inside your own column.

| Path | Surface | Owner |
|---|---|---|
| `app/`, `alembic/`, `tests/`, `requirements.txt`, `Dockerfile`, `docker-compose.prod.yml`, `Caddyfile` | Backend API | backend |
| `frontend/` | Web app + admin | frontend |
| `android-app/` | Android app | frontend |
| `landing/` | elchigo.uz static pages | frontend |
| `docs/`, `scripts/`, `README.md`, `RUNNING.md` | Shared | whoever changes the behaviour |

Needing to edit the other column is fine — it just means the other person reviews
that PR before it merges.

## Branches

`main` is always deployable. Nobody commits to it directly.

```
fe/<short-name>    frontend, Android, landing
be/<short-name>    API, migrations, deploy
```

Short names, lowercase, hyphens: `fe/driver-map-filters`, `be/order-cancel-endpoint`.

## The loop

```bash
git switch main && git pull            # start from a fresh main
git switch -c fe/driver-map-filters    # branch first, then write code
# ... commit as you go ...
git push -u origin HEAD
gh pr create                           # or open it in the GitHub UI
```

Keep a branch to one job. A branch that has been open for more than a couple of
days should be rebased on `main` so the merge stays boring:

```bash
git fetch origin && git rebase origin/main
```

## The API contract

`docs/API_GUIDE.md` is the agreement between the two sides.

- Backend: an endpoint that is added, renamed, or changes shape updates that file
  **in the same PR**. A PR that changes `app/api/` without touching it is incomplete.
- Frontend: read the endpoint from that file. If it is not written down, ask —
  do not guess from the code and do not go straight to the database.

## Before you open a PR

```bash
# backend
.venv/bin/python -m pytest

# frontend
cd frontend && npm run typecheck && npm run build
```

Say in the PR body what you changed and what you checked. If a migration is
included, say so — the other person has to run `alembic upgrade head` after pulling.
