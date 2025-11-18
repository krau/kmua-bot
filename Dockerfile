FROM ghcr.io/astral-sh/uv:debian-slim
WORKDIR /kmua
COPY pyproject.toml uv.lock ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ make build-essential git graphviz && \
    uv sync --frozen --no-dev && \
    apt-get purge -y --auto-remove gcc g++ make build-essential git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
COPY . .
ENTRYPOINT ["uv", "run", "python", "-m", "kmua"]
