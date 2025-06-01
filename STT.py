import os
import logging
import requests
from flask import Flask, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__, template_folder="templates")

# URL STT cần giữ ấm
STT_PING_URL = "https://stt-mu.vercel.app/api/ping"
PING_INTERVAL_MINUTES = 2  # ping mỗi 2 phút

# Cấu hình logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("keepalive_app")


def ping_stt_server():
    """
    Gửi GET đến STT_PING_URL. Nếu thành công (HTTP 200), log OK;
    nếu không, log cảnh báo hoặc lỗi tương ứng.
    """
    try:
        logger.info(f"▶ Gửi ping tới STT server: {STT_PING_URL}")
        resp = requests.get(STT_PING_URL, timeout=15)
        status = resp.status_code

        if status == 200:
            logger.info("✅ STT server đang hoạt động (HTTP 200).")
        else:
            logger.warning(f"⚠️ Ping trả về HTTP {status}. Response (cắt): {resp.text[:100]}")
    except Exception as e:
        logger.error(f"❌ Lỗi khi ping STT server: {e}")


@app.route("/")
def index():
    """
    Trả về trang HTML (index.html). Trang này chỉ để kiểm tra rằng 
    Flask instance đang chạy, không bắt buộc phải mở để cron hoạt động.
    """
    return render_template("bt.html")


@app.route("/keepalive", methods=["GET"])
def keepalive():
    """
    Khi được gọi (qua Cron hoặc thủ công), hàm này cũng gửi ping ngay lập tức
    đến STT_PING_URL và trả JSON kết quả để dễ debug.
    """
    try:
        logger.info(f"▶ (Manual) Ping STT server: {STT_PING_URL}")
        resp = requests.get(STT_PING_URL, timeout=15)
        status = resp.status_code

        if status == 200:
            return jsonify({"ok": True, "status_code": 200, "message": "STT server is awake"}), 200
        else:
            return jsonify({
                "ok": False,
                "status_code": status,
                "message": f"Ping returned HTTP {status}"
            }), 502

    except Exception as e:
        logger.error(f"❌ (Manual) Lỗi khi ping STT server: {e}")
        return jsonify({"ok": False, "status_code": -1, "message": f"Exception: {e}"}), 500


def start_scheduler():
    """
    Khởi BackgroundScheduler để tự động gọi ping_stt_server() mỗi 2 phút.
    """
    scheduler = BackgroundScheduler(daemon=True)
    # next_run_time=None để chạy lần đầu ngay lập tức khi container khởi
    scheduler.add_job(ping_stt_server, "interval", minutes=PING_INTERVAL_MINUTES, next_run_time=None)
    scheduler.start()
    logger.info(f"✅ Scheduler đã khởi, ping mỗi {PING_INTERVAL_MINUTES} phút.")


if __name__ == "__main__":
    # Trước hết khởi scheduler
    logger.info("Khởi tạo scheduler để tự động ping STT server...")
    start_scheduler()

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Keep-Alive Flask server chạy tại 0.0.0.0:{port}")
    # threaded=False để APScheduler không bị sự cố
    app.run(host="0.0.0.0", port=port, threaded=False)
