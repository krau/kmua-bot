FROM python:3.11.2-slim-bullseye
COPY . /kmua
WORKDIR /kmua
RUN apt-get update \
    && apt-get install -y lsb-release wget ttf-wqy-zenhei xfonts-intl-chinese \
    && pip install -r requirements.txt \
    && playwright install \
    && playwright install-deps
ENTRYPOINT [ "python","/kmua/bot.py" ]
