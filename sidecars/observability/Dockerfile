FROM python:3.11-slim

LABEL org.opencontainers.image.description="RUVAMCO Observability Sidecar"

RUN groupadd -r ruvamco && useradd -r -g ruvamco ruvamco

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN chown -R ruvamco:ruvamco /app
USER ruvamco

EXPOSE 8083

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8083/health')"

ENTRYPOINT ["python", "main.py"]
