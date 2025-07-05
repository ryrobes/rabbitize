FROM python:3.11-slim
WORKDIR /app

# Install system dependencies required for OpenCV and Tesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=True
ENV LOG_LEVEL=DEBUG
ENV OPENCV_ADAPTIVE_THRESH_GAUSSIAN_SIZE=3
ENV OPENCV_IO_MAX_IMAGE_PIXELS=100000000

# Run the application with increased timeout./test.
CMD exec gunicorn --bind :$PORT \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --threads 8 \
    --log-level info \
    --timeout 6000 \
    --graceful-timeout 6000 \
    --keep-alive 60 \
    main:app
