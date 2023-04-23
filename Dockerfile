FROM python:3.11.3-slim-bullseye
COPY . /kmua
WORKDIR /kmua
RUN pip install -r requirements.txt
ENTRYPOINT [ "python","/kmua/bot.py" ]
