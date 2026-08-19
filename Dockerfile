FROM python:3.12-slim

# --- 基本パッケージ ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
        jq \
    && rm -rf /var/lib/apt/lists/*

# --- warp-plus のインストール ---
# GitHub APIから動作環境(amd64/arm64)に合ったzipの直リンクを取得してダウンロード
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    DOWNLOAD_URL=$(curl -s https://api.github.com/repos/bepass-org/warp-plus/releases/latest \
        | jq -r ".assets[].browser_download_url" \
        | grep -i "linux" \
        | grep -i "$ARCH" \
        | grep -i "\.zip$" \
        | head -n 1); \
    if [ -z "$DOWNLOAD_URL" ]; then \
        echo "Error: Could not find download URL for architecture: $ARCH" && exit 1; \
    fi; \
    curl -fsSL -o /tmp/warp-plus.zip "$DOWNLOAD_URL"; \
    mkdir -p /opt/warp-plus; \
    unzip -o /tmp/warp-plus.zip -d /opt/warp-plus; \
    mv /opt/warp-plus/warp-plus /usr/local/bin/warp-plus; \
    chmod +x /usr/local/bin/warp-plus; \
    rm -rf /tmp/warp-plus.zip /opt/warp-plus

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# warp-plus のキャッシュ/設定ファイル用ディレクトリ
ENV WARP_PLUS_CACHE_DIR=/app/.warp-plus-cache
RUN mkdir -p ${WARP_PLUS_CACHE_DIR}

ENV USE_PROXY=true
ENV SOCKS5_PROXY_URL=socks5://127.0.0.1:8086

ENTRYPOINT ["./entrypoint.sh"]
