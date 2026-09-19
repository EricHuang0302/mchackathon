FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PYTHONPATH=/srv:/srv/agent \
    FIRST_AID_RULES_DIR=/srv/rules
WORKDIR /srv
COPY agent/pyproject.toml ./agent/pyproject.toml
COPY agent/app ./agent/app
COPY data ./data
COPY rules ./rules
WORKDIR /srv/agent
RUN pip install --no-cache-dir '.[live]'

RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "32", "--timeout", "0", "app.wsgi:app"]
