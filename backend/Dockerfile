# Build context: the REPOSITORY ROOT (see docker-compose.yml), so that the API
# image can include the ML code and model files it needs at runtime.
# The root .dockerignore allows only the files copied below into the context.
FROM python:3.14-slim

# Do not write .pyc files; flush logs immediately to the container output.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The image mirrors the repository layout (/auracinema/backend next to
# /auracinema/ml), so the backend finds the ML component at the same relative
# path as in a repository clone (app/services/recommendation_service.py, ML_DIR).
WORKDIR /auracinema/backend

# Install dependencies first so this layer is cached between code changes.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/alembic.ini .
COPY backend/alembic ./alembic
COPY backend/app ./app
# Maintenance scripts (catalogue seed, TMDB metadata), run on demand with
#   docker compose run --rm api python -m scripts.seed_movies
COPY backend/scripts ./scripts

# Runtime part of the ML component only: its Python package and the small
# versioned model files (CF neighbour matrix, item-index mapping, popularity
# ranking and their manifests, about 2.5 MB). The raw MovieLens data and the
# training/test datasets are never copied: recommendations do not need them.
COPY ml/src /auracinema/ml/src
COPY ml/data/models /auracinema/ml/data/models
# The movie catalogue read by scripts/seed_movies.py (about 300 KB). The
# training/test ratings in the same folder are still excluded.
COPY ml/data/processed/movies_catalogue.csv /auracinema/ml/data/processed/movies_catalogue.csv

# Run as an unprivileged user rather than root.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
