# AuraCinema — Backend (FastAPI)

REST API for AuraCinema: user accounts, JWT authentication, the movie catalogue
(MovieLens subset, with supplementary TMDB metadata stored locally), movie
ratings and a watchlist, backed by PostgreSQL.

All commands below are for **Windows PowerShell** and must be run from the
`backend/` folder.

## 1. Prerequisites

| Tool | Version used during development |
|---|---|
| Python | 3.14 (3.12+ expected to work; only 3.14 was tested) |
| Docker Desktop (with Docker Compose v2) | Docker 29.5, Compose 5.1 |

PostgreSQL does not need to be installed locally — it runs in a Docker container.

## 2. Create and activate the virtual environment

```powershell
cd backend          # from the repository root
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If activation is blocked by the execution policy, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt    # runtime + test/lint tools
# (requirements.txt alone is enough to run the API)
```

## 4. Configure environment variables

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Open `.env` and paste the generated value into `JWT_SECRET_KEY`. The API refuses
to start while the placeholder secret is still present. `.env` is git-ignored.

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development`, `test` or `production` |
| `DATABASE_URL` | PostgreSQL URL (`postgresql+psycopg://...`) for the application |
| `TEST_DATABASE_URL` | Separate database for automated tests (name must end in `_test`) |
| `JWT_SECRET_KEY` | Token signing secret, at least 32 characters |
| `JWT_ALGORITHM` | `HS256` (default), `HS384` or `HS512` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, 1–1440 (default 60) |
| `CORS_ORIGINS` | Comma-separated allowed browser origins (default `http://localhost:5173`) |
| `TMDB_API_READ_ACCESS_TOKEN` | Optional. TMDB "API Read Access Token", used only by the metadata scripts (the API never calls TMDB) |
| `TMDB_TIMEOUT_SECONDS` | Seconds to wait for one TMDB request (default 5, maximum 30) |
| `TMDB_METADATA_REFRESH_DAYS` | Stored metadata older than this is refreshed by the refresh script (default 30) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Used by Docker Compose to create the database |

## 5. Start PostgreSQL

```powershell
docker compose up -d db          # start the database container
docker compose ps                # wait until "db" shows (healthy)
docker compose logs -f db        # follow logs (Ctrl+C to exit)
```

On first start the container creates two databases: `auracinema` (development)
and `auracinema_test` (automated tests only).

## 6. Apply database migrations

```powershell
alembic upgrade head             # create/upgrade the schema
alembic current                  # show the applied revision
alembic history                  # list all migrations
alembic downgrade -1             # roll back the last migration (if needed)
```

After changing a model, generate a new migration and **review it** before applying:
`alembic revision --autogenerate -m "describe the change"`

### Import the movie catalogue

Ratings and watchlist entries must reference a catalogue movie, so import the
prepared catalogue (`../ml/data/processed/movies_catalogue.csv`, 5,068 movies,
produced by the ML data-preparation phase) after migrating:

```powershell
python -m scripts.seed_movies                       # default CSV location
python -m scripts.seed_movies --csv C:\path\to\movies_catalogue.csv
```

The import is safe to repeat: unchanged movies are skipped, and users, ratings
and watchlists are never modified. **Database that already has ratings or
watchlist entries** (created before the catalogue existed): `alembic upgrade head`
stops with an explanation, without changing data. Run instead:

```powershell
alembic upgrade 413ce2f03dd0      # create the movies table only
python -m scripts.seed_movies     # import the catalogue
alembic upgrade head              # add the foreign keys
```

### Fill and maintain the TMDB metadata

Overviews, release dates, runtimes and poster paths are stored in the
`movie_metadata` table. The API only reads that table, so it works (with null
metadata) even without a TMDB token, but then every poster is a placeholder and
`GET /movies/featured` answers 404.

**Every new environment** (new database or `docker compose down -v`) therefore
needs both scripts once, after `seed_movies`, with `TMDB_API_READ_ACCESS_TOKEN`
set. On 22 November 2026 the first full runs stored metadata for 5,047 of the
5,068 movies (20 TMDB IDs answer 404, 1 movie has no TMDB ID) and validated
4,981 IDs as `valid`.

The two scripts are separate operations: the refresh script stores the
content, and the validation script checks that each TMDB ID points to the
right movie.

```powershell
python -m scripts.refresh_movie_metadata              # new, failed or outdated metadata
python -m scripts.refresh_movie_metadata --limit 100  # only part of the work
python -m scripts.validate_tmdb_ids                   # check TMDB IDs not checked yet
python -m scripts.validate_tmdb_ids --recheck ambiguous
```

Both process movies in batches, save after every batch, respect TMDB rate
limits (HTTP 429 / `Retry-After`) and can be stopped with Ctrl+C and run again
to resume. Options: `--batch-size`, `--limit`, `--movie-id` (repeatable),
`--delay`, `--max-retries`; the refresh script also has `--refresh-days`.
Use `--help` for details.

## 7. Run the API

```powershell
uvicorn app.main:app --reload
```

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- Liveness: <http://127.0.0.1:8000/health> — readiness (checks DB): <http://127.0.0.1:8000/health/ready>

### Trying the API in Swagger

1. `POST /api/v1/auth/register` with `{"email": "you@example.com", "password": "at-least-15-characters", "name": "Your Name"}` (the name is required).
2. Click **Authorize** (top right), enter the email as *username* and the password, then **Authorize**.
3. Call the protected endpoints, e.g. `PUT /api/v1/ratings/318` with `{"rating": 4.5}`.

Movie endpoints are public:

- `GET /api/v1/movies?search=the%20matrix&genre=Sci-Fi`: search ignores case,
  accents, punctuation and MovieLens trailing articles. `genre` (optional) must
  be a name returned by `GET /api/v1/movies/genres`. Every item includes
  `display_title` ("The Matrix"), `year` and the stored `poster_url`.
- `GET /api/v1/movies/genres`: the catalogue genres with their movie counts.
- `GET /api/v1/movies/featured`: the movie featured on Discover today. It is a
  daily rotation over movies with a poster, an overview and a validated TMDB ID,
  not a popularity ranking.
- `GET /api/v1/movies/1` and `GET /api/v1/movies/1/details`: stored overview and
  poster; `metadata_status` explains missing metadata.

Account endpoints (login required; the user is always the token's user):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/users/me` | Account and profile (`name`, `location`, `bio`) |
| `PATCH /api/v1/users/me` | Change only the profile fields sent; `""`/`null` clears location or bio |
| `PUT /api/v1/users/me/email` | `{"new_email", "current_password"}`; 403 wrong password, 409 email taken |
| `PUT /api/v1/users/me/password` | `{"current_password", "new_password"}`; 204, or 403 wrong password |
| `GET /api/v1/users/me/stats` | Rating count, average and per-genre statistics for the Profile page |

`GET /api/v1/ratings` and `GET /api/v1/watchlist` include each `movie` (title,
display title, genres, poster), so lists need no request per movie.

### Recommendations

`GET /api/v1/recommendations?limit=10` (login required, `limit` 1–20) returns
the user's recommendations. Users with at least 2 ratings that are not all
identical get item-based collaborative filtering (`"source":
"collaborative_filtering"`). Everyone else gets the popularity baseline
(`"source": "popularity"`, with a cold-start `message`). Movies the user has
rated are never returned; watchlist movies can be.

The API loads the trained models once at start-up from the versioned folder
`../ml/data/models/`. It holds the CF neighbour matrix, the
`movie_index_map.csv` mapping, the popularity ranking and their manifests,
about 2.5 MB in total. Nothing is retrained, and the git-ignored MovieLens
training/test datasets are not needed, so recommendations work in a fresh clone
and in Docker. The log shows `Collaborative filtering model loaded` and
`Popularity baseline loaded`. If a model cannot be loaded, the API still starts:
the reason is logged and only this endpoint answers `503`. Details:
`docs/recommendation_service_integration.md`.

### Alternative: run API and database in Docker

The catalogue import runs from the host (it needs the CSV from `ml/`), using the
`DATABASE_URL` in `.env`, which points to the published port `127.0.0.1:5432`.

```powershell
docker compose up -d --build     # builds the API image, applies migrations, starts both
docker compose logs -f api
docker compose down              # stop and remove containers (data volume is kept)
docker compose down -v           # ALSO deletes the database volume (all data!)
```

Stop the API container before running `uvicorn` locally, since both use port 8000.
The image is built from the **repository root**
(`context: ..` in `docker-compose.yml`). It contains the backend code plus the
runtime part of the ML component (`ml/src` and `ml/data/models`), in the same
folder layout as the repository. The root `.dockerignore` allows only those
paths, so the MovieLens datasets never enter the build context or the image.

## 8. Run the automated tests

PostgreSQL must be running (step 5). Tests use `TEST_DATABASE_URL` only; the
test database schema is dropped and rebuilt from the migrations on each run.

```powershell
pytest                                           # all tests
pytest -v tests/unit                             # unit tests only (no database needed)
pytest --cov=app --cov=scripts --cov-report=term-missing   # with coverage report
```

Linting and formatting: `ruff check .` and `ruff format .`

## 9. Troubleshooting

| Problem | Cause / solution |
|---|---|
| `ValidationError ... jwt_secret_key ... placeholder` | Generate a real secret in `.env` (step 4). |
| `ValidationError ... database_url` | URL must start with `postgresql+psycopg://`. |
| Commands hang or time out connecting to the database | Use `127.0.0.1`, not `localhost`, in the URLs: on Windows `localhost` may resolve to IPv6 (`::1`), while Docker publishes the port on IPv4 only. |
| `connection refused` / `/health/ready` returns 503 | Database container is not running: `docker compose up -d db`. |
| Port 5432 already in use | A local PostgreSQL is running; stop it or change the host port in `docker-compose.yml` and `.env`. |
| `database "auracinema_test" does not exist` | The init script only runs on a new volume. Create it manually: `docker compose exec db psql -U auracinema -c "CREATE DATABASE auracinema_test"` |
| `Refusing to run: test database name ... must end with '_test'` | Safety guard: point `TEST_DATABASE_URL` to a dedicated test database. |
| `Activate.ps1 cannot be loaded` | See execution policy note in step 2. |
| `RuntimeError: Cannot add the movie foreign keys` | Existing ratings/watchlist rows reference movies not yet imported. Follow the three commands in "Import the movie catalogue". |
| `the database schema is missing or outdated` (import or metadata scripts) | Run `alembic upgrade head` (or `alembic upgrade 413ce2f03dd0` on a database that already has user data, see above) first. |
| `PUT /ratings/{id}` or `/watchlist/{id}` returns 404 `Movie not found` | The ID is not in the catalogue; import it or use a catalogue `movie_id`. |
| `metadata_status` is `not_imported`, posters are all placeholders, or `/movies/featured` returns 404 | Run `python -m scripts.refresh_movie_metadata`, then `python -m scripts.validate_tmdb_ids` (the featured movie needs a `valid` ID). |
| `GET /movies?genre=...` returns 422 `Unknown genre` | Use a name exactly as returned by `GET /movies/genres` (e.g. `Sci-Fi`, not `scifi`). |
| A metadata script prints `TMDB_API_READ_ACCESS_TOKEN is not set` or stops with `TMDB rejected the request (auth_failed)` | Set or correct `TMDB_API_READ_ACCESS_TOKEN` in `.env` (use the long *Read Access Token*, not the short *API Key*). |
| Accented titles look wrong (e.g. `LÃ©on`) in Windows PowerShell 5.1 | Display issue of PowerShell 5.1's `Invoke-WebRequest`; the data is correct UTF-8. Use Swagger UI or a browser. |
| `GET /recommendations` returns 503 | A model file in `ml/data/models/` could not be loaded at start-up; the server log shows which one and why (e.g. a hash mismatch means the file was changed or does not belong to this model). Restore the committed files (`git checkout -- ../ml/data/models`) and restart the API. |
| VS Code shows "package not installed" hints | Select the interpreter `backend\.venv\Scripts\python.exe` (Ctrl+Shift+P → *Python: Select Interpreter*). |
