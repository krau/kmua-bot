FROM python:3.11.4-slim-bullseye
COPY . /kmua
WORKDIR /kmua
RUN apt-get update && apt-get install graphviz -y && pip install -r requirements.txt
ENTRYPOINT [ "python","/kmua/bot.py" ]
