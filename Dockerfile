FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install torch + torchvision from the CPU wheel index first so the
# regular `pip install` below picks them up instead of pulling the CUDA
# build (~800MB) from PyPI as a transitive dependency of ultralytics.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.0,<2.5" "torchvision>=0.15"

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Pre-download YOLOv8n weights so the smart-reframe step doesn't pay a
# cold-start network cost on the first request.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
