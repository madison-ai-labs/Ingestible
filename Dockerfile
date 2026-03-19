FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ingestible/templates/ /app/templates/
COPY src/ingestible/static/ /app/static/

ENV INGEST_DATA_DIR=/data

EXPOSE 8081

CMD ["uvicorn", "ingestible.api:app", "--host", "0.0.0.0", "--port", "8081"]
