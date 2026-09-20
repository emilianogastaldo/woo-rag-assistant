FROM python:3.12.14-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS build
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.lock ./
RUN pip install -r requirements.lock
COPY pyproject.toml ./
COPY app ./app
RUN python -m build --wheel --no-isolation --outdir /wheels \
    && pip install --no-deps /wheels/*.whl && pip check

FROM build AS runtime
# Source is deliberately absent from runtime cwd: imports exercise the installed wheel.
RUN rm -rf /build/app
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=7s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=6)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
