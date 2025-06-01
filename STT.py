import os
import uuid
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr
import time
import logging

# --- Cấu hình Flask App và Logging ---
app = Flask(__name__, template_folder="templates")

# Cấu hình logging chính
app.logger.setLevel(logging.INFO)

# --- Cấu hình chung ---
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Giới hạn 5MB
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

# --- Routes ---
@app.route("/", methods=["GET"])
def index():
    """Trang chủ hiển thị giao diện Web Speech API"""
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET / from {request.remote_addr}")
    return render_template("STT.html")

@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """API endpoint nhận file WAV từ ESP32, parse và trả transcript"""
    request_received_time = time.time()
    request_id = str(uuid.uuid4())
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] POST /api/transcribe from {request.remote_addr}")

    if "audio_data" not in request.files:
        app.logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Missing 'audio_data'.")
        return jsonify({"error": "Missing audio file"}), 400

    audio_file = request.files["audio_data"]
    if not audio_file.filename.lower().endswith(".wav"):
        app.logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Invalid file type: {audio_file.filename}")
        return jsonify({"error": "Invalid file type, expecting .wav"}), 400

    temp_filename = f"{request_id}.wav"
    temp_path = os.path.join(TMP_DIR, temp_filename)

    try:
        save_start_time = time.time()
        audio_file.save(temp_path)
        file_size = os.path.getsize(temp_path)
        app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Saved to {temp_path} ({file_size} bytes) in {time.time() - save_start_time:.2f}s")

        recognizer = sr.Recognizer()
        transcript_text = ""

        with sr.AudioFile(temp_path) as source:
            record_start_time = time.time()
            audio_data = recognizer.record(source)
            app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Audio data loaded in {time.time() - record_start_time:.2f}s")

            try:
                recognize_start_time = time.time()
                transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
                app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Transcript: '{transcript_text}' in {time.time() - recognize_start_time:.2f}s")
            except sr.UnknownValueError:
                app.logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Google Speech couldn’t understand audio.")
                transcript_text = ""
            except sr.RequestError as e:
                app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Google Speech API error: {e}")
                return jsonify({"error": f"Speech recognition service error: {e}"}), 500
            except Exception as e_rec:
                app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Recognition error: {e_rec}")
                return jsonify({"error": f"Recognition processing error: {e_rec}"}), 500

    except Exception as e_file:
        app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] File save/process error: {e_file}")
        return jsonify({"error": f"File processing error: {e_file}"}), 500
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Removed temp file {temp_path}")
            except Exception as e_del:
                app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Del temp file error: {e_del}")

    total_time = time.time() - request_received_time
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Finished /api/transcribe in {total_time:.2f}s")
    return jsonify({"transcript": transcript_text})

@app.route("/api/ping", methods=["GET"])
def ping():
    """Endpoint đơn giản để kiểm tra server STT (keep-warm)"""
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/ping from {request.remote_addr}")
    return jsonify({"status": "alive", "timestamp": time.time()}), 200

# Vercel yêu cầu biến 'application' để deploy Flask
application = app

if __name__ == '__main__':
    app.run(debug=True)
