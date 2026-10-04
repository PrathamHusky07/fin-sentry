FROM python:3.13-slim

WORKDIR /app

# build-essential: some requirements (e.g. sentencepiece/tokenizers on some
# platforms) fall back to a source build if no prebuilt wheel matches.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm

COPY finsentry/ ./finsentry/
COPY config/ ./config/

ENV PYTHONUNBUFFERED=1
# The input rail models (Llama Guard 3 1B, Llama Prompt Guard 2 86M) and the
# retrieval embedding model (bge-small-en-v1.5) are loaded from a mounted
# host Hugging Face cache (see docker-compose.dev.yml) -- offline mode skips
# the Hub's own "is this still the latest revision" network round trip,
# which would otherwise run on every one of three replicas' startup for
# models that are not going to change during a local demo.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

EXPOSE 8000

CMD ["uvicorn", "finsentry.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
