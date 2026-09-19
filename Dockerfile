FROM python:3.11-slim

ARG UPSTREAM_COMMIT=9beeb721c2af551bacaab827a76bddaecaa0ca5e
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UPSTREAM_ROOT=/opt/upstream

RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt requirements-langchain.txt requirements-llama.txt requirements-crewai.txt ./

RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

RUN python -m venv /opt/venvs/langchain \
    && /opt/venvs/langchain/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venvs/langchain/bin/pip install -r requirements-langchain.txt \
    && /opt/venvs/langchain/bin/pip check

RUN python -m venv /opt/venvs/llama \
    && /opt/venvs/llama/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venvs/llama/bin/pip install -r requirements-llama.txt \
    && /opt/venvs/llama/bin/pip check

RUN python -m venv /opt/venvs/crewai \
    && /opt/venvs/crewai/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venvs/crewai/bin/pip install -r requirements-crewai.txt \
    && /opt/venvs/crewai/bin/pip check

RUN git clone https://github.com/ashishpatel26/500-AI-Agents-Projects.git /opt/upstream \
    && cd /opt/upstream \
    && git checkout "$UPSTREAM_COMMIT" \
    && test "$(git rev-parse HEAD)" = "$UPSTREAM_COMMIT" \
    && rm -rf /opt/upstream/.git

COPY app ./app

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
