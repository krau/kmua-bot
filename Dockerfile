FROM python:3.9
COPY . /kmua
WORKDIR /kmua
RUN apt-get update \
    && apt-get install -y lsb-release wget ttf-wqy-zenhei xfonts-intl-chinese \
    && wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && dpkg -i ./google-chrome-stable_current_amd64.deb \
    && apt-get -f install google-chrome-stable \
    && rm google-chrome-stable_current_amd64.deb \
    && pip install -r requirements.txt
ENTRYPOINT [ "python","/kmua/bot.py" ]
