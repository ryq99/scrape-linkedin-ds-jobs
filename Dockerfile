FROM python:3.9-slim-buster 

RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    wget \
    gnupg \
    libgconf-2-4 \
    libfontconfig \
    firefox-esr \
    xvfb \
    x11vnc

# Set up Firefox driver
RUN mkdir /drivers && \
    wget -O /drivers/geckodriver https://github.com/mozilla/geckodriver/releases/download/v0.32.2/geckodriver-v0.32.2-linux64.tar.gz && \
    tar -xvzf /drivers/geckodriver -C /drivers && \
    chmod +x /drivers/geckodriver && \
    mv /drivers/geckodriver /usr/local/bin/

# Set up XVFB display
ENV DISPLAY=:99
EXPOSE 5900

WORKDIR /app

COPY requirements.txt requirements.txt
COPY config.yml config.yml 
COPY scrape.py scrape.py 

RUN pip install -r requirements.txt 

CMD ["python", "scrape.py"]

# Start VNC server
#CMD x11vnc -display :99 -forever -rfbport 5900 -passwd 06020602

#docker run -it -v "/Users/ruichenyang/projects/ds_jobs:/app" ds_scrape bash 