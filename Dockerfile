FROM python:3.9
COPY . /kmua
WORKDIR /kmua
RUN apt update && apt upgrade \
    && apt install -y lsb-release wget ttf-wqy-zenhei xfonts-intl-chinese \
    && wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt install -y google-chrome-stable_current_amd64.deb \
    && pip install -r requirements.txt
ENTRYPOINT [ "python","/kmua/bot.py" ]