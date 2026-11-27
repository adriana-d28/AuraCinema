# AuraCinema

AuraCinema is a movie discovery web application. It recommends movies based on
what you have rated, and it lets you decide **how adventurous** those
recommendations should be.

Most recommendation systems try to show you more of what you already like.
AuraCinema does that too, but it adds a **Discovery Mode** with three settings:
Safe, Balanced and Adventurous. They let you trade some predictability for
movies that are less obvious, less popular and more varied, while still
connected to your taste.

The project is a full-stack application: a React website, a Python REST API, a
PostgreSQL database and a machine-learning recommendation engine trained on the
MovieLens 32M dataset. Everything runs in Docker containers and is ready to be
deployed to a cloud server. It was developed as the final project of the Higher
Diploma in Science in Computing at the National College of Ireland.

---

## Contents

1. [Features](#features)
2. [How it works](#how-it-works)
3. [The recommendation engine](#the-recommendation-engine)
4. [Technology stack](#technology-stack)
5. [Repository structure](#repository-structure)
6. [Getting started](#getting-started)
7. [Loading the movie data](#loading-the-movie-data)
8. [Configuration](#configuration)
9. [Running the tests](#running-the-tests)
10. [Reproducing the machine-learning pipeline](#reproducing-the-machine-learning-pipeline)
11. [Deployment](#deployment)
12. [Security](#security)
13. [Data sources, licences and attribution](#data-sources-licences-and-attribution)
14. [Limitations](#limitations)
15. [References](#references)

---

## Features

| Feature | What you can do |
|---|---|
| **Account** | Register with a name, email and password, log in and log out. |
| **Discover** | See a featured movie of the day, browse the whole catalogue and filter it by genre. |
| **Search** | Find movies by title. Search ignores capital letters, accents and punctuation, and understands MovieLens titles such as "Matrix, The" (so "the matrix" works). |
| **Movie details** | See the poster, plot overview, release date, runtime and genres of a movie, and its MovieLens average rating (also shown on every movie card). |
| **Ratings** | Rate movies from 0.5 to 5 stars (half stars allowed), change or remove a rating. |
| **Watchlist** | Save movies to watch later and remove them again. |
| **Recommendations** | Get a personalised list of up to 20 movies, based on your ratings. |
| **Discovery Mode** | Choose Safe, Balanced or Adventurous to control how far the recommendations move away from your usual choices. |
| **Profile** | See your details, your most recent ratings and your rating statistics: how many movies you rated, your average rating, and how you rate each genre. |
| **Settings** | Edit your name, location and bio, upload a profile picture, and change your email or password. |

A few behaviours worth knowing:

- **New users** have no rating history yet, so they receive the most popular
  movies, with a message explaining that recommendations become personal as
  they rate movies.
- **Movies you have rated are never recommended** again. Movies on your
  watchlist can still be recommended.
- **Your profile is private.** Only you can see your profile, ratings,
  watchlist and picture.

---

## How it works

AuraCinema follows a client-server architecture with four parts:

```
Browser
   │
   ▼
┌──────────────────────────┐
│  web  (Caddy)            │   Serves the React website and forwards /api requests.
│                          │   Provides HTTPS on a real domain.
└────────────┬─────────────┘
             │ /api/*
             ▼
┌──────────────────────────┐
│  api  (FastAPI)          │   Accounts, ratings, watchlist, catalogue, recommendations.
│  + ML models in memory   │   The trained models are loaded once, at start-up.
└────────────┬─────────────┘
             │ SQL
             ▼
┌──────────────────────────┐
│  db  (PostgreSQL)        │   Users, ratings, watchlist, movie catalogue, TMDB metadata.
└──────────────────────────┘
```

- The **website** (React + TypeScript) never talks to the database or to
  external services. It only calls the AuraCinema API.
- The **API** (FastAPI) owns all the rules: who is logged in, what each user
  may see, and how recommendations are built. It stores everything in
  PostgreSQL.
- The **recommendation engine** is a Python package in `ml/`. It is trained
  offline, and the API loads the trained model files from `ml/data/models/`
  when it starts. Recommendations are computed in milliseconds, inside the
  API process.
- **Movie information** comes from two places. MovieLens gives the catalogue
  (titles, genres, identifiers, average ratings). TMDB (The Movie Database) gives the posters,
  plot overviews, release dates and runtimes. TMDB data is downloaded by
  maintenance scripts and **stored in PostgreSQL**, so the website keeps
  working even if TMDB is slow or unavailable.

### What happens when you ask for recommendations

1. The website sends `GET /api/v1/recommendations` with your login token.
2. The API identifies you from the token and reads **your** ratings from the
   database.
3. If you have enough history, the collaborative filtering model ranks the
   movies you have not rated. Otherwise the popularity ranking is used.
4. If you chose a Discovery Mode, a re-ranking step reorders the
   personalised candidates.
5. The API adds the movie titles, genres and posters, and returns the list.

---

## The recommendation engine

### The data

AuraCinema uses the **MovieLens 32M** dataset from GroupLens Research: 32
million ratings from about 200,000 users, collected between 1995 and 2023.

The full dataset has more than 84,000 rated movies, but most of them have very
few ratings, which makes similarities between them unreliable. AuraCinema
therefore uses a **fixed catalogue of 5,068 movies**:

- the 5,000 most-rated movies, plus
- the 100 most-rated movies of every genre (so that less popular genres such
  as Film-Noir and Western keep enough titles).

These 5,068 movies still hold about 91% of all ratings. Users with at least 20
ratings in the catalogue are kept: 198,391 users and 29 million ratings.

The ratings are split **chronologically for each user**. The oldest 80% of
each user's ratings are used for training, and the most recent 20% are kept
for testing. This mirrors the real task: predicting what someone will like
next from what they liked before.

### Popularity baseline

The popularity model ranks the catalogue by the **number of ratings** each
movie received in the training data. It is not personal: everyone gets the
same list, minus the movies they have already rated.

It has two jobs:

- it is the benchmark that the personalised model has to beat;
- it is the fallback for new users (see "Cold start" below).

### Item-based collaborative filtering

The personalised model is **item-based collaborative filtering** (Sarwar et
al., 2001). The idea is simple: two movies are similar if the same people
tend to like (or dislike) both of them.

1. **Remove personal rating scales.** Each rating is turned into a deviation
   from that user's own average, so a generous rater and a strict rater who
   agree on which movies are better look alike.
2. **Measure movie similarity** with the *adjusted cosine* similarity between
   the movies' rating columns.
3. **Keep the 50 most similar movies** for each movie (only positive
   similarities). This removes noise and keeps the model small.
4. **Score your unrated movies.** A movie gets a higher score when it is
   similar to movies you rated above your own average:
   `score(movie) = Σ similarity(movie, rated movie) × (your rating − your average)`.

The score is used only to **rank** movies. It is not a predicted star rating,
so the website shows positions, never the score itself.

### How well does it work?

Both models were evaluated on the held-out test ratings of 195,687 users. A
movie counts as relevant when the user rated it 3.5 or higher.

| Metric (top 10) | Popularity | Collaborative filtering | Improvement |
|---|---|---|---|
| Precision@10 | 0.066 | **0.105** | +59.5% |
| Recall@10 | 0.051 | **0.084** | +65.2% |
| NDCG@10 | 0.080 | **0.132** | +63.6% |
| Catalogue coverage | 6.2% | **82.8%** | |

Collaborative filtering beats the popularity baseline on every metric at K =
5, 10 and 20. It also reaches far more of the catalogue: its top-10 lists
include 82.8% of the 5,068 movies, against 6.2% for popularity.

### Cold start

A model that learns from your ratings cannot say much about you before you
have rated anything. This is the **cold-start** problem.

AuraCinema switches to collaborative filtering once you have **at least 2
ratings that are not all the same**. With a single rating, or with identical
ratings, every deviation from your average is zero, so the model has nothing
to learn from. Before that point you see the popularity list, with a message
explaining why.

### Discovery Mode

Discovery Mode is not a second model. Collaborative filtering first selects
your **100 best candidates**, and Discovery Mode then **reorders** them. Every
recommendation therefore still comes from your personal candidates.

The list is built one position at a time. At each step, the candidate with
the highest value is chosen:

```
value = (1 − w) × relevance + w × (½ × novelty + ½ × diversity)
```

- **Relevance:** how high the movie is in your collaborative filtering
  ranking.
- **Novelty:** how rarely the movie has been rated. Less-known movies are more
  novel.
- **Diversity:** how different the movie's genres are from the movies already
  in the list.
- **w** is the exploration weight of the mode: **Safe 0.15, Balanced 0.35,
  Adventurous 0.6**. With Discovery Mode off, you get the plain
  collaborative filtering order.

The weights were fixed before any measurement and were not tuned. Measured on
10,000 test users (top 10):

| Mode | NDCG@10 | Novelty (bits) | Genre diversity | Same movies as plain CF |
|---|---|---|---|---|
| Off (plain CF) | 0.130 | 2.83 | 0.74 | 100% |
| Safe | 0.126 | 2.95 | 0.77 | 90% |
| Balanced | 0.112 | 3.27 | 0.82 | 71% |
| Adventurous | 0.083 | 4.03 | 0.86 | 38% |
| *Popularity (for comparison)* | *0.083* | *1.53* | *0.78* | *19%* |

Each step towards Adventurous gives more novel and more varied lists, at the
cost of some accuracy. Even the Adventurous lists are as accurate as the
popularity ranking (NDCG 0.083), while being much more novel (4.03 bits
against 1.53).

---

## Technology stack

| Area | Technology | Why it was chosen and what it brings |
|---|---|---|
| **Frontend** | React 19 + TypeScript 7 | React builds the interface from reusable components (movie cards, posters, star ratings). TypeScript checks the data exchanged with the API at compile time, so mistakes such as a misspelled field are caught before they reach the browser. |
| | Vite 8 | Development server with instant reloads, and the production build that turns the React code into plain HTML, CSS and JavaScript (the `dist/` folder). |
| | React Router 8 | Gives each page its own address (`/watchlist`, `/movies/318`), so pages can be bookmarked and the back button works. |
| | CSS Modules + design tokens | Styles are scoped to one component, so they cannot clash, and colours, spacing and fonts are defined once as CSS variables. No extra styling library is needed. |
| **Backend** | Python 3.14 + FastAPI | The same language as the machine-learning code, so the API can load and run the models directly. FastAPI validates every request from Python type hints and generates interactive API documentation (Swagger UI) automatically. |
| | Pydantic + pydantic-settings | Validates request bodies (for example a rating must be 0.5 to 5 in half steps) and the configuration in `.env`. The API refuses to start with an unsafe setting, such as a placeholder secret. |
| | Uvicorn | The ASGI server that runs the FastAPI application. |
| **Database** | PostgreSQL 17 | A reliable relational database. Its constraints (unique keys, foreign keys, checks) protect the data even if the application code has a bug: a rating can never point to a movie outside the catalogue. |
| | SQLAlchemy 2 + psycopg 3 | SQLAlchemy maps database tables to Python classes and builds safe, parameterised queries, which prevents SQL injection. psycopg is the PostgreSQL driver. |
| | Alembic | Versioned database migrations: every schema change is a script that can be applied, checked and rolled back. |
| **Security** | Argon2id (pwdlib) + JWT (PyJWT) | Argon2id is the recommended algorithm for storing passwords. JWT access tokens let the website prove who the user is on every request without server-side sessions. |
| | Pillow | Checks that an uploaded profile picture really is an image and stores a new, clean JPEG (resized, without hidden metadata such as GPS location). |
| **Machine learning** | NumPy, pandas, SciPy | pandas prepares and validates the 32 million ratings. SciPy's sparse matrices make the item-item similarity computation practical (about one minute on a laptop), and NumPy does the fast vectorised scoring. The trained model is a small compressed `.npz` file, about 2.5 MB together with its manifests. |
| **External data** | TMDB API (+ httpx2) | TMDB provides posters and movie details that MovieLens does not have. The data is fetched by scripts and stored in PostgreSQL, so user requests never depend on TMDB. |
| **Containers** | Docker + Docker Compose | One command starts the whole application with the same versions on any machine, from a laptop to a cloud server. |
| | Caddy | Serves the website, forwards `/api` to the API and obtains HTTPS certificates automatically when a domain is configured. |
| **Testing and quality** | pytest, Vitest + Testing Library, Ruff, oxlint | Automated tests for the API, the database, the services, the scripts and the ML code (pytest), and for the React components (Vitest). Ruff and oxlint keep the Python and TypeScript code consistent. |

---

## Repository structure

```
AuraCinema/
├── backend/                  FastAPI application
│   ├── app/
│   │   ├── api/routes/       HTTP endpoints (auth, users, movies, ratings, watchlist, recommendations, health)
│   │   ├── core/             Configuration, security (hashing, JWT), title normalisation
│   │   ├── db/               Database engine and sessions
│   │   ├── models/           SQLAlchemy tables
│   │   ├── schemas/          Pydantic request and response models
│   │   └── services/         Business logic (accounts, ratings, catalogue, TMDB, recommendations)
│   ├── alembic/              Database migrations
│   ├── scripts/              Maintenance scripts: catalogue import, TMDB metadata refresh and validation
│   ├── tests/                Unit, integration and API tests
│   ├── docker-compose.yml    The db, api and web containers
│   ├── Dockerfile            API image (includes the ML runtime and the model files)
│   └── README.md             Detailed backend guide (all options and troubleshooting)
├── frontend/                 React application
│   ├── src/
│   │   ├── pages/            One component per page (Discover, Recommendations, Watchlist, ...)
│   │   ├── components/       Reusable interface components
│   │   ├── auth/             Login state and protected routes
│   │   ├── services/api/     Typed functions that call the API
│   │   └── styles/           Design tokens and global styles
│   ├── Dockerfile            Website image (Node build stage + Caddy)
│   └── Caddyfile             Web server configuration
└── ml/                       Recommendation engine
    ├── src/                  Data preparation, popularity baseline, collaborative filtering,
    │                         Discovery Mode, offline evaluation
    ├── tests/                ML tests
    └── data/
        ├── models/           Trained models used by the API (versioned)
        ├── evaluation/       Evaluation results (versioned)
        └── processed/        Prepared data; only movies_catalogue.csv is versioned
```

---

## Getting started

There are two ways to run AuraCinema:

- **With Docker only** (simplest): everything runs in containers. Use this to
  try the application or to deploy it.
- **For development**: the database runs in Docker, while the API and the
  website run on your machine with live reloading.

### Prerequisites

| Tool | Needed for | Version used |
|---|---|---|
| Git | Getting the code | any recent version |
| Docker Desktop (or Docker Engine with the Compose plugin) | Both ways | Docker 29, Compose 5 |
| Python | Development only | 3.14 |
| Node.js (with npm) | Development only | 24 |

You also need a free **TMDB account** if you want posters and movie details
(see [Loading the movie data](#loading-the-movie-data)). The application works
without it, but every poster is then a placeholder.

### Option A: run everything with Docker

```bash
git clone https://github.com/adriana-d28/AuraCinema.git
cd AuraCinema/backend

# 1. Create your configuration file from the template
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```

Open `backend/.env` and replace `JWT_SECRET_KEY` with a random value. You can
generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then start the three containers and load the catalogue:

```bash
# 2. Build and start the database, the API and the website
docker compose --profile web up -d --build

# 3. Import the 5,068-movie catalogue (only needed once)
docker compose run --rm api python -m scripts.seed_movies
```

Open **http://localhost**, create an account and start rating movies.

Useful commands:

```bash
docker compose ps                      # see the containers and their status
docker compose logs -f api             # follow the API log
docker compose --profile web down      # stop everything (your data is kept)
```

The API applies the database migrations automatically every time it starts.

> **After changing frontend code**, rebuild the website container to see the
> change: `docker compose --profile web up -d --build web`. The container
> holds a built copy of the site and does not follow code changes.

### Option B: development setup

**1. Database** (from `backend/`, after creating `.env` as in Option A):

```bash
docker compose up -d db
```

On its first start, the container creates two databases: `auracinema` for
the application and `auracinema_test` for the automated tests.

**2. API** (from `backend/`):

```bash
python -m venv .venv
source .venv/bin/activate           # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

alembic upgrade head                # create the database tables
python -m scripts.seed_movies       # import the movie catalogue
uvicorn app.main:app --reload       # start the API on http://127.0.0.1:8000
```

The interactive API documentation is at **http://127.0.0.1:8000/docs**. There
you can try every endpoint: register, click **Authorize**, log in, and call the
protected endpoints.

**3. Website** (from `frontend/`, in a second terminal):

```bash
npm install
npm run dev                         # start the website on http://localhost:5173
```

The website expects the API at `http://127.0.0.1:8000/api/v1`. To use another
address, copy `frontend/.env.example` to `frontend/.env` and change
`VITE_API_BASE_URL`.

> On Windows, use `127.0.0.1` instead of `localhost` in database and API
> addresses. `localhost` can resolve to IPv6 first, while Docker publishes its
> ports on IPv4, which makes connections hang.

The [backend README](backend/README.md) describes every option, endpoint and
common error in detail.

---

## Loading the movie data

A new database needs three steps. Only the first one is required.

| Step | Command (from `backend/`) | What it does |
|---|---|---|
| 1. Catalogue | `python -m scripts.seed_movies` | Imports the 5,068 movies (titles, genres, MovieLens/IMDb/TMDB identifiers) from `ml/data/processed/movies_catalogue.csv`, with each movie's MovieLens average rating and rating count from `ml/data/models/popularity_baseline.csv`. Safe to repeat: unchanged movies are skipped and user data is never touched. |
| 2. Metadata | `python -m scripts.refresh_movie_metadata` | Downloads the poster, overview, release date and runtime of each movie from TMDB and stores them. |
| 3. Validation | `python -m scripts.validate_tmdb_ids` | Checks that each TMDB identifier points to the right movie (same title and year). The "featured movie" on Discover only uses validated movies. |

In Docker, run the same commands through the API container, for example
`docker compose run --rm api python -m scripts.refresh_movie_metadata`.

Steps 2 and 3 need a TMDB token:

1. Create a free account at [themoviedb.org](https://www.themoviedb.org/) and
   request an API key in your account settings.
2. Copy the **API Read Access Token** (the long one, starting with `eyJ`),
   not the shorter API key.
3. Paste it into `TMDB_API_READ_ACCESS_TOKEN` in `backend/.env`.

The scripts work in batches and save after every batch. They respect TMDB's
rate limits, and you can stop them with Ctrl+C and run them again to resume.
A full first run stores metadata for 5,047 of the 5,068 movies: TMDB does not
know 20 of the identifiers, and one movie has no TMDB identifier. Run the
refresh script again from time to time: it only updates metadata older than
30 days.

---

## Configuration

All backend settings are read from `backend/.env`. The template
`backend/.env.example` explains each value. The main ones are:

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development`, `test` or `production` |
| `DATABASE_URL` | PostgreSQL address used by the API |
| `TEST_DATABASE_URL` | Separate database for the tests (its name must end in `_test`) |
| `JWT_SECRET_KEY` | Secret used to sign login tokens, at least 32 characters |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | How long a login lasts (default 60 minutes) |
| `CORS_ORIGINS` | Browser addresses allowed to call the API (default: the Vite dev server) |
| `TMDB_API_READ_ACCESS_TOKEN` | Optional. Used only by the metadata scripts |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Used by Docker Compose to create the database |
| `SITE_ADDRESS` | Address of the website container: `:80` locally, or a domain on a server |
| `COMPOSE_PROFILES` | Set to `web` on a server so the website starts with `docker compose up` |

`.env` files are never committed. Only the `.env.example` templates are.

---

## Running the tests

| Part | Command | Tests |
|---|---|---|
| Backend | `cd backend` then `pytest` | 552 |
| Machine learning | `cd ml` then `python -m pytest` | 110 |
| Frontend | `cd frontend` then `npm test` | 17 |

The **backend tests** need the database container (`docker compose up -d db`).
They only use the `auracinema_test` database: its tables are rebuilt from the
migrations on every run. As a safety check, the tests refuse to run against a
database whose name does not end in `_test`.

The backend tests cover:

- **Unit tests:** settings, validation rules, password hashing and tokens,
  title normalisation, the TMDB client.
- **Integration tests:** database constraints, migrations, services, the
  maintenance scripts, and loading the real model files.
- **API tests:** every endpoint, including user isolation (one user can never
  see or change another user's data).
- **Security tests:** SQL injection attempts, and checks that passwords,
  tokens and secrets never appear in responses or logs.

The **ML tests** check the data pipeline, the models and the evaluation code,
including checks that the test data never leaks into training.

Code style:

| Part | Lint | Format / type check |
|---|---|---|
| Backend | `ruff check .` | `ruff format .` |
| Frontend | `npm run lint` | `npm run typecheck` |

---

## Reproducing the machine-learning pipeline

You do **not** need this to run the application: the trained models are
already in `ml/data/models/`. Follow these steps only to rebuild the models
or repeat the evaluation.

1. Download **MovieLens 32M** (`ml-32m.zip`) from
   [grouplens.org/datasets/movielens](https://grouplens.org/datasets/movielens/)
   and extract it to `ml/data/ml-32m/`.
2. Install the dependencies (from `ml/`):

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows PowerShell: .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Run the pipeline (from `ml/`):

   | Command | What it does | Time |
   |---|---|---|
   | `python -m src.prepare_data --overwrite` | Verifies and cleans the dataset, selects the catalogue, creates the train/test split | ~3.5 min |
   | `python -m src.popularity_baseline --overwrite` | Builds the popularity ranking | seconds |
   | `python -m src.collaborative_filtering --overwrite` | Trains the collaborative filtering model | ~1 min |
   | `python -m src.evaluate_recommendations evaluate` | Compares both models on the test set | ~4 min |
   | `python -m src.evaluate_recommendations discovery` | Measures the three Discovery Mode settings | |

The scripts refuse to replace existing files unless you pass `--overwrite`.
Every output comes with a manifest that records the SHA-256 hashes of its
inputs. If the API is given a model file that does not match its manifest, it
refuses to load it and logs the reason, instead of serving wrong
recommendations. The rest of the application keeps working, and only the
recommendations endpoint answers 503.

Training needs about 3 GB of memory.

---

## Deployment

The containers are ready for a single cloud server, such as an AWS EC2
instance. On the server:

1. **Open the ports** in the server's firewall (on AWS, the security group):
   22 for SSH, 80 and 443 for the website.
2. **Get a domain name** that points to the server's IP address. A free
   subdomain from [Duck DNS](https://www.duckdns.org/) works. On AWS, an
   Elastic IP keeps the address fixed when the instance restarts.
3. **Install Docker** and make it start with the machine:
   `sudo systemctl enable --now docker`.
4. **Clone the repository** and create `backend/.env` with production values:
   - `APP_ENV=production`;
   - a new `JWT_SECRET_KEY` and a strong `POSTGRES_PASSWORD`;
   - `CORS_ORIGINS=https://your-domain`;
   - `SITE_ADDRESS=your-domain`;
   - `COMPOSE_PROFILES=web`.
5. **Start and load the data:**

   ```bash
   cd backend
   docker compose up -d --build
   docker compose run --rm api python -m scripts.seed_movies
   docker compose run --rm api python -m scripts.refresh_movie_metadata
   docker compose run --rm api python -m scripts.validate_tmdb_ids
   ```

With a domain in `SITE_ADDRESS`, Caddy obtains a free HTTPS certificate from
Let's Encrypt, renews it automatically, and redirects HTTP to HTTPS.

All containers use `restart: unless-stopped`, so they come back on their own
after a crash or a server reboot. Only the website container is reachable from
the internet: the API and the database listen on the server's local address
only.

---

## Security

- **Passwords** are hashed with Argon2id and never stored, logged or returned.
  They must have at least 15 characters.
- **Login tokens** (JWT) are signed with a secret from the configuration and
  expire after 60 minutes. The website keeps the token in `sessionStorage`,
  so closing the browser tab ends the session.
- **Every protected endpoint identifies the user from the token.** A user ID
  sent by the client is never trusted, so one user cannot read or change
  another user's ratings, watchlist or profile.
- **Changing the email or the password requires the current password.**
- **Input is validated twice:** by Pydantic in the API and by database
  constraints in PostgreSQL. All queries are parameterised by SQLAlchemy.
- **Errors never reveal internal details,** such as database addresses or
  stack traces.
- **Profile pictures** are decoded and re-encoded as a new 512×512 JPEG. Files
  that are not images (including SVG) and files over 2 MB are rejected.
- **CORS** allows only the configured website addresses, and wildcard
  origins are refused.
- **Secrets** live only in `.env` files, which are git-ignored. The API
  refuses to start with the example secret.

---

## Data sources, licences and attribution

**MovieLens.** The ratings and the movie catalogue come from the MovieLens 32M
dataset by GroupLens Research, University of Minnesota (Harper and Konstan,
2015). The dataset is used for non-commercial research and education, under
its usage licence. The catalogue file in `ml/data/processed/` is a
transformation of the dataset and is redistributed under the same licence (see
[ml/data/processed/README.md](ml/data/processed/README.md)). AuraCinema is not
endorsed by the University of Minnesota or GroupLens.

**TMDB.** Posters, overviews, release dates and runtimes come from The Movie
Database (TMDB).

<img src="frontend/src/assets/tmdb-logo.svg" alt="TMDB logo" height="12">

This product uses the TMDB API but is not endorsed or certified by TMDB.

AuraCinema uses TMDB under the non-commercial terms. Stored metadata is
refreshed well within TMDB's caching limits, and TMDB data is not used to
train the recommendation models.

---

## Limitations

- **Fixed catalogue.** Only the 5,068 selected movies can be rated or
  recommended. Novelty in Discovery Mode is relative to this catalogue, which
  leans towards well-known titles.
- **No retraining from app users.** The model learns from MovieLens users.
  Ratings made in AuraCinema personalise your recommendations immediately, but
  they do not change the similarities between movies until the model is
  retrained.
- **Offline evaluation.** The results above come from historical MovieLens
  data. They show which method ranks held-out ratings better, not how real
  users would react.
- **Discovery Mode weights** are reasoned design choices, not values learned
  from user feedback.

---

## References

- Carbonell, J. and Goldstein, J. (1998) 'The use of MMR, diversity-based
  reranking for reordering documents and producing summaries', *Proceedings of
  the 21st Annual International ACM SIGIR Conference*, pp. 335–336.
  https://doi.org/10.1145/290941.291025
- Cremonesi, P., Koren, Y. and Turrin, R. (2010) 'Performance of recommender
  algorithms on top-N recommendation tasks', *Proceedings of the Fourth ACM
  Conference on Recommender Systems*, pp. 39–46.
  https://doi.org/10.1145/1864708.1864721
- Ekstrand, M.D., Riedl, J.T. and Konstan, J.A. (2011) 'Collaborative
  filtering recommender systems', *Foundations and Trends in Human–Computer
  Interaction*, 4(2), pp. 81–173. https://doi.org/10.1561/1100000009
- Harper, F.M. and Konstan, J.A. (2015) 'The MovieLens datasets: history and
  context', *ACM Transactions on Interactive Intelligent Systems*, 5(4),
  pp. 19:1–19:19. https://doi.org/10.1145/2827872
- Järvelin, K. and Kekäläinen, J. (2002) 'Cumulated gain-based evaluation of
  IR techniques', *ACM Transactions on Information Systems*, 20(4),
  pp. 422–446. https://doi.org/10.1145/582415.582418
- Kaminskas, M. and Bridge, D. (2016) 'Diversity, serendipity, novelty, and
  coverage: a survey and empirical analysis of beyond-accuracy objectives in
  recommender systems', *ACM Transactions on Interactive Intelligent Systems*,
  7(1), Article 2. https://doi.org/10.1145/2926720
- Sarwar, B., Karypis, G., Konstan, J. and Riedl, J. (2001) 'Item-based
  collaborative filtering recommendation algorithms', *Proceedings of the 10th
  International Conference on World Wide Web*, pp. 285–295.
  https://doi.org/10.1145/371920.372071
- Zhou, T., Kuscsik, Z., Liu, J.-G., Medo, M., Wakeling, J.R. and Zhang, Y.-C.
  (2010) 'Solving the apparent diversity-accuracy dilemma of recommender
  systems', *Proceedings of the National Academy of Sciences*, 107(10),
  pp. 4511–4515. https://doi.org/10.1073/pnas.1000488107
- Ziegler, C.-N., McNee, S.M., Konstan, J.A. and Lausen, G. (2005) 'Improving
  recommendation lists through topic diversification', *Proceedings of the
  14th International Conference on World Wide Web*, pp. 22–32.
  https://doi.org/10.1145/1060745.1060754

---

**Author:** Adriana Souza Dinelly. Final project, Higher Diploma in Science
in Computing, National College of Ireland, 2026.
