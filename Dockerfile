# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=main.py \
    APP_ENV=production

# Set work directory
WORKDIR /app

# Install system dependencies for database drivers and media libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt /app/
RUN pip install --upgrade 'pip>=26.2' && \
    pip install -r requirements.txt gunicorn

# Copy the rest of the application
COPY --chown=10001:10001 . /app/

# Create necessary directories for volumes (ensure they have correct permissions)
RUN useradd --uid 10001 --create-home app && \
    mkdir -p /app/instance /app/static/uploads/comics /app/static/uploads/covers && \
    chown -R app:app /app/instance /app/static/uploads && \
    chmod 700 /app/instance && chmod -R 750 /app/static/uploads

USER app

# Expose port 5000
EXPOSE 5000

# Start Gunicorn (using main.py's create_app by default)
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--timeout", "120", "main:create_app()"]
