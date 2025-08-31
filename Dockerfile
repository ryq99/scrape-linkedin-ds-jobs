FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install Chromium browser and dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    ca-certificates 

RUN apt-get install -y \
    chromium \
    chromium-driver \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/bin:$PATH"

WORKDIR /app
COPY src/ src/
COPY requirements.txt requirements.txt

RUN pip install -U pip
RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python3", "src/scrape.py"]