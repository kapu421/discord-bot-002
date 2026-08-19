#!/bin/bash
set -e

PROXY_BIND="${PROXY_BIND:-127.0.0.1:8086}"
CACHE_DIR="${WARP_PLUS_CACHE_DIR:-/app/.warp-plus-cache}"

echo "[entrypoint] starting warp-plus (SOCKS5 on ${PROXY_BIND}) ..."

# -b: SOCKS5バインドアドレス
# -c: キャッシュ/鍵の保存先（root権限不要な場所を指定）
warp-plus -b "${PROXY_BIND}" -c "${CACHE_DIR}" &
WARP_PID=$!

# main.py 側で keep_alive() のFlaskサーバーがすぐ立つように、
# warp-plus の起動完了を待たずに並行してBotプロセスも起動する。
# プロキシ待機（＝Discordログイン前の待ち合わせ）は main.py 側で行う。
echo "[entrypoint] starting Discord bot (health check server opens immediately)..."
python3 main.py &
BOT_PID=$!

# どちらかが終了したらもう片方も止めて終了する
trap 'kill -TERM "$WARP_PID" "$BOT_PID" 2>/dev/null || true' TERM INT

wait -n "$WARP_PID" "$BOT_PID"
EXIT_CODE=$?
kill -TERM "$WARP_PID" "$BOT_PID" 2>/dev/null || true
exit "$EXIT_CODE"
