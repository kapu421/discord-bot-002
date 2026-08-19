FROM python:3.12-slim

# --- 基本パッケージ ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# --- warp-plus のインストール ---
# bepass-org/warp-plus はユーザー空間WireGuard実装(netstack)で動作するため、
# /dev/net/tun や root/CAP_NET_ADMIN が無いRenderの無権限コンテナでも動作する。
# バージョンは固定してビルドを再現可能にする（必要に応じて更新してください）。
ARG WARP_PLUS_VERSION=v1.2.5
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "$ARCH" in \
        amd64) WP_ARCH="linux-amd64" ;; \
        arm64) WP_ARCH="linux-arm64" ;; \
        *) echo "unsupported architecture: $ARCH" && exit 1 ;; \
    esac; \
    # リリースのアセット名が存在しない場合にビルドを失敗させないようにする
    if curl -fsSL -o /tmp/warp-plus.zip \
        "https://github.com/bepass-org/warp-plus/releases/download/${WARP_PLUS_VERSION}/warp-plus_${WARP_PLUS_VERSION#v}_${WP_ARCH}.zip"; then \
        unzip -o /tmp/warp-plus.zip -d /opt/warp-plus; \
        mv /opt/warp-plus/warp-plus /usr/local/bin/warp-plus; \
        chmod +x /usr/local/bin/warp-plus; \
        rm -rf /tmp/warp-plus.zip /opt/warp-plus; \
    else \
        echo "WARNING: warp-plus asset not found for ${WARP_PLUS_VERSION} (arch=${WP_ARCH}), skipping installation."; \
    fi

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# warp-plus のキャッシュ/設定ファイルを書けるように(root権限が無くても書き込める場所)
ENV WARP_PLUS_CACHE_DIR=/app/.warp-plus-cache
RUN mkdir -p ${WARP_PLUS_CACHE_DIR}

# デフォルトではプロキシを使わない設定にしておく（必要ならデプロイ時に環境変数で上書き）
ENV USE_PROXY=false
ENV SOCKS5_PROXY_URL=socks5://127.0.0.1:8086

ENTRYPOINT ["./entrypoint.sh"]
