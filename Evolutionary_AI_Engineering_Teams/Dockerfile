FROM python:3.12-slim

WORKDIR /app

# Deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source (see .dockerignore — secrets and .env are NOT copied in)
COPY . .

ENV PYTHONUNBUFFERED=1 \
    SERVE_HOST=0.0.0.0

EXPOSE 8765

# GCP creds (for Claude via Vertex) and runtime config are provided at RUN time,
# never baked into the image: mount ADC at $GOOGLE_APPLICATION_CREDENTIALS and
# pass MONGO_URI / GEMINI_API_KEY via --env-file. With no GCP creds the judge
# falls back to the Gemini API-key backend automatically.
CMD ["python", "-u", "cli.py", "serve"]
