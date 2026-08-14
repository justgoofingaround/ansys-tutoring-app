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
COPY server/ server/
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
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
