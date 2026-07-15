FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Installa le dipendenze separatamente per sfruttare la cache dei layer.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Il codice viene montato come volume in sviluppo (docker-compose),
# ma lo copiamo comunque per build/immagini stand-alone.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
