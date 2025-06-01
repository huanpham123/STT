import os
import uuid
import time
import logging
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr
from werkzeug.utils import secure_filename
from flask_cors import CORS

# --- Cấu hình Flask App và Logging ---
app = Flask(__name__, template_folder="templates")
CORS(app)  # Cho phép CORS (nếu cần gọi từ trình duyệt khác gốc)

app.logger.setLevel(logging.INFO)

# --- Cấu hình chung ---
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Giới hạn kích thước file upload 5MB
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"wav"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# --- Routes ---
@app.route("/", methods=["GET"])
def index():
    """
    Trang chủ: trả về giao diện STT.html (dùng cho Web Speech API demo)
    Nếu bạn chỉ dùng ESP32, không bắt buộc phải lên root, có thể bỏ qua.
    """
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET request to / from {request.remote_addr}")
    return render_template("STT.html")


@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """
    API endpoint để ESP32 (hoặc client khác) gửi WAV và nhận kết quả chuyển thành text.
    Trả về JSON: {"transcript": "<nội dung nhận dạng>"}
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())
    client_ip = request.remote_addr or "Unknown"

    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] POST /api/transcribe from {client_ip}")

    # Kiểm tra file
    if "audio_data" not in request.files:
        app.logger.warning(f"[ReqID: {request_id}] Missing 'audio_data' in request.files.")
        return jsonify({"error": "Missing audio file (audio_data)"}), 400

    file = request.files["audio_data"]
    filename = secure_filename(file.filename or "")
    if not filename:
        app.logger.warning(f"[ReqID: {request_id}] Empty filename.")
        return jsonify({"error": "Invalid filename"}), 400

    if not allowed_file(filename):
        app.logger.warning(f"[ReqID: {request_id}] Invalid file extension: {filename}")
        return jsonify({"error": "Invalid file type. Only .wav allowed"}), 400

    # Lưu tạm file vào TMP_DIR với uuid
    temp_filename = f"{request_id}.wav"
    temp_path = os.path.join(TMP_DIR, temp_filename)
    try:
        file.save(temp_path)
        file_size = os.path.getsize(temp_path)
        app.logger.info(f"[ReqID: {request_id}] Saved file to {temp_path} ({file_size} bytes)")
    except Exception as e:
        app.logger.error(f"[ReqID: {request_id}] Error saving file: {e}")
        return jsonify({"error": f"File saving failed: {str(e)}"}), 500

    # Thực hiện nhận dạng giọng nói
    transcript_text = ""
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_path) as source:
            audio_data = recognizer.record(source)
            app.logger.info(f"[ReqID: {request_id}] Loaded audio data, length={audio_data.duration_seconds:.2f}s")

            try:
                transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
                app.logger.info(f"[ReqID: {request_id}] Transcript: {transcript_text}")
            except sr.UnknownValueError:
                app.logger.warning(f"[ReqID: {request_id}] Google Speech Recognition could not understand audio.")
                transcript_text = ""
            except sr.RequestError as e_rec:
                app.logger.error(f"[ReqID: {request_id}] Recognition service error: {e_rec}")
                return jsonify({"error": f"Speech recognition service error: {str(e_rec)}"}), 500
            except Exception as e_other:
                app.logger.error(f"[ReqID: {request_id}] Unexpected error during recognition: {e_other}")
                return jsonify({"error": f"Recognition processing failed: {str(e_other)}"}), 500

    finally:
        # Xóa file tạm
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                app.logger.info(f"[ReqID: {request_id}] Temporary file {temp_path} deleted.")
        except Exception as e_del:
            app.logger.error(f"[ReqID: {request_id}] Error deleting temp file: {e_del}")

    elapsed = time.time() - start_time
    app.logger.info(f"[ReqID: {request_id}] Finished /api/transcribe in {elapsed:.2f}s")

    return jsonify({"transcript": transcript_text})


@app.route("/api/ping", methods=["GET"])
def ping():
    """
    Endpoint để ESP32 ping check và keep-alive (warm-up) serverless.
    Trả về JSON {"status":"alive", "timestamp": <epoch>}
    """
    now_ts = time.time()
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/ping from {request.remote_addr}")
    return jsonify({"status": "alive", "timestamp": now_ts}), 200


# --- Main ---
# Khi deploy lên Vercel, Flask sẽ không chạy __main__.
# Khi chạy local (python STT.py), app.run() mới active.
if __name__ == "__main__":
    # debug=True chỉ nên dùng trong local dev, không nên bật khi deploy production
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
