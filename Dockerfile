FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATABASE_URL=sqlite:////data/credit_eval.db

# Fixed non-root uid. /data must belong to it: an empty named volume mounted
# there inherits this ownership, and SQLite needs to write in that directory.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data \
    && chown app:app /data

WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS builder

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && pip install --no-cache-dir -r requirements.txt


# Used by docker compose: runtime + dev tools + tests, so the README commands work.
FROM builder AS dev

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY pytest.ini .
COPY app/ app/
COPY tests/ tests/

# /app is read-only for the app user: keep pytest from writing its cache there.
ENV PYTEST_ADDOPTS="-p no:cacheprovider"

USER 10001


# Last stage, so a plain `docker build .` produces the minimal image.
FROM base AS runtime

COPY --from=builder /opt/venv /opt/venv
COPY app/ app/

USER 10001
