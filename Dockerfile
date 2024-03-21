FROM python:3.12.2-slim-bookworm
COPY . /kmua
WORKDIR /kmua
RUN apt-get update && apt-get install graphviz -y && pip install -r requirements.txt
ENTRYPOINT [ "python","-m","kmua" ]
