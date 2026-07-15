FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Installa le dipendenze sfruttando la cache dei layer: si usa un package
# stub così `pip install .` risolve le dipendenze senza il codice reale.
# Questo layer viene ricostruito solo quando cambia pyproject.toml.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --upgrade pip && pip install .

# Il codice viene montato come volume in sviluppo (docker-compose),
# ma lo copiamo comunque per build/immagini stand-alone.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
