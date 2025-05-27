FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
COPY . /kmua
WORKDIR /kmua
RUN apt-get update && \
    apt-get install -y gcc g++ make build-essential graphviz && \
    uv sync --frozen --no-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["uv", "run", "python", "-m", "kmua"]
