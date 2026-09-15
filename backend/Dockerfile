# Use an official lightweight Python image
FROM python:3.11-slim

# Prevent Python from writing .pyc files & buffer stdout/stderr for real-time logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install system dependencies (needed for compiling C-extensions if using numpy/scipy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment to isolate dependencies and silence pip root warning
RUN python -m venv /opt/venv

# Copy dependencies first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Download ONNX quantized weights (~80MB) and tokenizer files during build
RUN mkdir -p app/providers/embeddings/model_onnx && \
    curl -L -o app/providers/embeddings/model_onnx/model.onnx https://huggingface.co/optimum/all-MiniLM-L6-v2/resolve/main/model.onnx && \
    curl -L -o app/providers/embeddings/model_onnx/tokenizer.json https://huggingface.co/optimum/all-MiniLM-L6-v2/resolve/main/tokenizer.json

# Copy application source code
COPY . .

# Expose container port
EXPOSE 8000

# Run Gunicorn with Uvicorn async workers for production scaling
CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker -w ${WORKERS:-1} -b 0.0.0.0:${PORT:-10000} app.main:app"]
