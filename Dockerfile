FROM python:3.12-slim

# --- 基本パッケージ ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# --- warp-plus のインストール ---
# 最新タグを動的に取得してダウンロードURLの不一致エラーを回避
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "$ARCH" in \
        amd64) WP_ARCH="linux-amd64" ;; \
        arm64) WP_ARCH="linux-arm64" ;; \
        *) echo "unsupported architecture: $ARCH" && exit 1 ;; \
    esac; \
    LATEST_TAG=$(curl -s https://api.github.com/repos/bepass-org/warp-plus/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/'); \
    VERSION_NUM="${LATEST_TAG#v}"; \
    curl -fsSL -o /tmp/warp-plus.zip "https://github.com/bepass-org/warp-plus/releases/download/${LATEST_TAG}/warp-plus_${VERSION_NUM}_${WP_ARCH}.zip"; \
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
