# JARVIS as a Hugging Face Space (Docker SDK) — or any container host.
#
# Runs the web app (FastAPI + PWA) with the Hugging Face Inference backend, so
# both the brain (a model served by HF) and the app live in the cloud. Set the
# HF_TOKEN secret in the Space; optionally set JARVIS_WEB_TOKEN to gate access.
FROM python:3.11-slim

# Hugging Face Spaces run the container as uid 1000 — match it and give that
# user a writable home so config/memory has somewhere to live.
RUN useradd -m -u 1000 user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    JARVIS_PROVIDER=hf \
    JARVIS_WEB_HOST=0.0.0.0 \
    JARVIS_WEB_PORT=7860 \
    JARVIS_NO_BROWSER=1 \
    JARVIS_DATA_DIR=/home/user/.jarvis

WORKDIR /home/user/app

# Install deps first for better layer caching.
COPY --chown=user:user requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

COPY --chown=user:user . .

USER user
EXPOSE 7860

# Serves on 0.0.0.0:7860 (HF Spaces' expected port); no browser auto-open.
CMD ["python", "-m", "jarvis.web"]
