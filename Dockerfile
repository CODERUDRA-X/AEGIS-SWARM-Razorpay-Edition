# AEGIS-SWARM Razorpay Edition :: Backend Dockerfile
# ======================================================
# REUSED PATTERN from AEGIS v1's Dockerfile: python:3.10-slim base,
# same install-requirements-then-copy-app layer ordering (for Docker
# layer caching), same HF Spaces port convention (7860) if deployed
# there. Adjust CMD's --port if deploying elsewhere (e.g. Render/Railway
# typically inject $PORT).

FROM python:3.10-slim

WORKDIR /app

# Install dependencies first (layer-cached across builds that only change app code)
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy application code, dataset, and any pre-trained model artifact
COPY app/ ./app/
COPY data/ ./data/
COPY models/ ./models/

# Ensure the models directory is writable (baseline model is trained
# on first request if no .pkl exists yet -- see app/main.py::get_model())
RUN mkdir -p models && chmod 777 models

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
