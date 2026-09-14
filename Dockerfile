# Tutoring Hub — cloud image (team-testing deployments, ENABLE_LLM=0).
# Stage 1: build the React SPA.
FROM node:20-slim AS webapp
WORKDIR /build
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build

# Stage 2: Python runtime serving API + built SPA.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Compass document search: NYU pilot only (WITH_COMPASS=1 from
# deploy/docker-compose.yml); cloud images skip it. CPU-only torch, the
# retrieval libraries, and the embedding model (matches EMBEDDING_MODEL in
# chatbot_spike/config.py) are baked in so nothing downloads at runtime. The
# index itself is mounted from the host (chatbot_spike/data, not in git).
ARG WITH_COMPASS=0
COPY requirements-compass.txt ./
RUN if [ "$WITH_COMPASS" = "1" ]; then \
      pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.12.1 \
      && pip install --no-cache-dir -r requirements-compass.txt \
      && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"; \
    fi

COPY server/ server/
COPY chatbot_spike/ chatbot_spike/
RUN if [ "$WITH_COMPASS" != "1" ]; then rm -rf chatbot_spike; fi
COPY tools/validate_tutorial.py tools/validate_tutorial.py
COPY mock_server/data/ mock_server/data/
COPY --from=webapp /build/dist webapp/dist
# Ollama-backed LLM features off in the cloud (no Ollama); every LLM path
# degrades gracefully. The Compass chatbot AND PDF->tutorial conversion CAN
# run in the cloud: set CHATBOT_API_KEY (+ optional CHATBOT_API_BASE /
# CHATBOT_MODEL, defaulting to Groq's free tier) to route them through an
# OpenAI-compatible API — no retrieval index for chat, general-knowledge
# answers, demo-grade only.
# Instructor account comes from INSTRUCTOR_USERNAME / INSTRUCTOR_PASSWORD
# env vars at deploy time.
ENV ENABLE_LLM=0 \
    SEED_ALL_TUTORIALS=1 \
    DATA_DIR=/app/server_data \
    PYTHONUNBUFFERED=1 \
    ANONYMIZED_TELEMETRY=False \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
# ANONYMIZED_TELEMETRY=False: chromadb reports usage events by default.
# HF_*_OFFLINE=1: the embedding model is baked in; never call Hugging Face.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
