FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
COPY . /kmua
WORKDIR /kmua
RUN apt-get update && apt-get install graphviz -y && uv sync --frozen --no-dev
ENTRYPOINT ["uv", "run", "python", "-m", "kmua"]
