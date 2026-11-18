FROM python:3.10-slim

# Install system dependencies including FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and assets
COPY . .

# Create data directories
RUN mkdir -p /app/data/storage /app/test_pack/outputs

ENV PORT=8000
ENV HOST=0.0.0.0
ENV ENVIRONMENT=production
ENV STT_PROVIDER=mock
ENV LLM_PROVIDER=rule_based

EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "api/app.py"]

