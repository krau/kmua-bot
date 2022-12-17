FROM python:3.9
COPY . /kmua
WORKDIR /kmua
RUN sudo apt-get update && sudo apt-get upgrade -y \
    && sudo apt-get install -y lsb-release wget ttf-wqy-zenhei xfonts-intl-chinese \
    && sudo wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && sudo apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && sudo pip install -r requirements.txt
CMD [ "python","/kmua/bot.py" ]
