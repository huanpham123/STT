import os
import uuid
import time
import logging
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr

app = Flask(__name__, template_folder="templates")

# Cấu hình logging chi tiết hơn
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = app.logger # Sử dụng logger của Flask

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Giới hạn kích thước file upload là 5MB
TMP_DIR = "/tmp"  # Vercel cho phép ghi vào /tmp

# Đảm bảo thư mục /tmp tồn tại (quan trọng cho môi trường serverless)
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def index():
    logger.info(f"GET / from {request.remote_addr}")
    return render_template("STT.html")

@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    request_id = str(uuid.uuid4())
    logger.info(f"[ReqID:{request_id}] POST /api/transcribe from {request.remote_addr}")

    if "audio_data" not in request.files:
        logger.warning(f"[ReqID:{request_id}] Missing audio file in request")
        return jsonify({"error": "Missing audio file"}), 400

    audio_file = request.files["audio_data"]

    if not audio_file.filename or not audio_file.filename.lower().endswith(".wav"):
        logger.warning(f"[ReqID:{request_id}] Invalid file type or no filename. Allowed: .wav. Filename: {audio_file.filename}")
        return jsonify({"error": "Invalid file type, .wav only"}), 400

    # Sử dụng request_id để tạo tên file duy nhất, tránh xung đột
    temp_path = os.path.join(TMP_DIR, f"{request_id}_{audio_file.filename}")

    try:
        audio_file.save(temp_path)
        logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Audio saved to {temp_path}")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_path) as source:
            logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Processing audio file...")
            audio_data = recognizer.record(source) # Đọc toàn bộ file audio
            logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Audio data recorded from file. Attempting recognition...")
            
            try:
                # Sử dụng Google Web Speech API để nhận dạng tiếng Việt
                transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
                logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Transcription successful: {transcript_text}")
            except sr.UnknownValueError:
                logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Google Speech Recognition could not understand audio")
                transcript_text = ""  # Trả về chuỗi rỗng nếu không nhận dạng được
            except sr.RequestError as e:
                logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Could not request results from Google Speech Recognition service; {e}")
                return jsonify({"error": f"Speech API error: {e}"}), 500
            
    except Exception as e:
        logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] File processing error: {e}", exc_info=True)
        return jsonify({"error": f"File processing error: {e}"}), 500
    finally:
        # Dọn dẹp file tạm sau khi xử lý
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Temp file {temp_path} removed")
            except Exception as e_remove:
                logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] Error removing temp file {temp_path}: {e_remove}")


    return jsonify({"transcript": transcript_text})

@app.route("/api/ping", methods=["GET"])
def ping():
    logger.info(f"GET /api/ping from {request.remote_addr} - Server is alive.")
    return jsonify({"status": "alive", "timestamp": time.time()}), 200

# Vercel yêu cầu biến 'application' hoặc 'app' để deploy Flask
application = app # Hoặc app nếu bạn cấu hình vercel.json dùng app

if __name__ == "__main__":
    # Chạy ở local development, Vercel sẽ không dùng phần này
    # Chạy với threaded=True để xử lý nhiều request đồng thời tốt hơn (cho local test)
    app.run(debug=True, threaded=True, port=5000)
