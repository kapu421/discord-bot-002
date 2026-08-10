import os
import logging
from threading import Thread

from flask import Flask

logger = logging.getLogger(__name__)

app = Flask('')

# Flaskの標準ログを抑制（UptimeRobotのアクセスログでコンソールが埋まらないように）
logging.getLogger('werkzeug').setLevel(logging.ERROR)


@app.route('/')
def home():
    return "I'm alive!"


def run():
    port = int(os.environ.get("PORT", 8080))  # Renderが割り当てるPORTを使う
    app.run(host='0.0.0.0', port=port)


def keep_alive():
    t = Thread(target=run)
    t.daemon = True  # メインプロセス終了時に一緒に終了させる
    t.start()
    logger.info("keep_alive: Flask server started for UptimeRobot pings.")
