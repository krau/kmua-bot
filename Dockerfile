FROM python:3.12.4-slim-bookworm
COPY . /kmua
WORKDIR /kmua
RUN apt-get update && apt-get install graphviz -y && pip install poetry && poetry install --without dev
ENTRYPOINT [ "poetry", "run", "python", "-m","kmua"]
