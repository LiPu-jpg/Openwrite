FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OPENWRITE_RESOURCE_ROOT=/usr/local/share/openwrite

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/openwrite
COPY . /opt/openwrite

RUN pip install --no-cache-dir -e /opt/openwrite

RUN mkdir -p /usr/local/share/openwrite \
    && cp -R /opt/openwrite/craft /usr/local/share/openwrite/craft \
    && cp -R /opt/openwrite/skills /usr/local/share/openwrite/skills \
    && cp -R /opt/openwrite/tools/resources/defaults/language_packs /usr/local/share/openwrite/language_packs

WORKDIR /workspace

ENTRYPOINT ["smart-story-openwrite-adapter"]
