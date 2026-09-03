FROM python:3.12-slim

# Prevent buffering and bytecode generation
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user
RUN useradd --create-home --shell /bin/bash --uid 10001 appuser

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files with proper ownership
COPY --chown=appuser:appuser tracker/ ./tracker/
COPY --chown=appuser:appuser apps/ ./apps/
COPY --chown=appuser:appuser main.py server.py ./

# Switch to non-root user
USER appuser

EXPOSE 8000

# Default: 24x7 FastAPI webhook server (K3s Deployment)
# Can be overridden by K3s CronJob with: command: ["python", "main.py"]
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
