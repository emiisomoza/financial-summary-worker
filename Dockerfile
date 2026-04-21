FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/
COPY templates/ ./templates/

# Create non-root user (security: minimal privilege)
RUN useradd -m -u 1000 worker && \
    mkdir -p /app/data && \
    chown -R worker:worker /app

USER worker

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "worker.main"]
