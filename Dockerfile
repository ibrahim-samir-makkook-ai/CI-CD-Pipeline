# Use official lightweight Python image
FROM python:3.11-slim

# Prevent Python from writing .pyc and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the application
COPY . .

EXPOSE 5000

# Healthcheck for local & CI smoke tests
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# Production: use gunicorn (installed via requirements.txt)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
