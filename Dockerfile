# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=main.py \
    FLASK_ENV=production

# Set work directory
WORKDIR /app

# Install system dependencies (needed for packages like Pillow, PyPDF2, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install -r requirements.txt gunicorn

# Copy the rest of the application
COPY . /app/

# Create necessary directories for volumes (ensure they have correct permissions)
RUN mkdir -p /app/instance /app/static/uploads/comics /app/static/uploads/covers && \
    chmod -R 777 /app/instance /app/static/uploads

# Expose port 5000
EXPOSE 5000

# Start Gunicorn (using main.py's create_app by default)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--timeout", "120", "main:create_app()"]
