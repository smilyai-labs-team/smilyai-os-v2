FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        qemu-system-x86 \
        qemu-utils \
        novnc \
        websockify \
        gh \
        jq \
        unzip \
        ca-certificates \
        procps \
    && rm -rf /var/lib/apt/lists/*
