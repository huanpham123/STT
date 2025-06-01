import os
import uuid
import time
import logging
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr
import threading

app = Flask(__name__, template_folder="templates")
app.logger.setLevel(logging.INFO)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

# ========================================
# === KHỞI TẠO SỚM RECOGNIZER - TRÁNH DELAY ===
# ========================================
class RecognizerPool:
    def __init__(self, pool_size=3):
        self.pool = [sr.Recognizer() for _ in range(pool_size)]
        self.lock = threading.Lock()
        self.warm_up_recognizers()
    
    def warm_up_recognizers(self):
        """Warm-up recognizers to avoid cold start delays"""
        def warm_up(recognizer):
            try:
                with sr.AudioFile(os.devnull) as source:
                    recognizer.record(source)
            except Exception:
                pass
        
        threads = []
        for r in self.pool:
            t = threading.Thread(target=warm_up, args=(r,))
            t.start()
            threads.append(t)
        
        for t in threads:
            t.join()

    def get_recognizer(self):
        with self.lock:
            return self.pool.pop() if self.pool else sr.Recognizer()
    
    def return_recognizer(self, recognizer):
        with self.lock:
            if len(self.pool) < 10:  # Giới hạn pool size
                self.pool.append(recognizer)

# Tạo pool ngay khi khởi động server
recognizer_pool = RecognizerPool()

# ========================================
# === CƠ CHẾ TỰ WARM-UP ĐỊNH KỲ (MỖI 4 PHÚT) ===
# ========================================
def auto_warm_up():
    while True:
        app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🔥 Performing auto warm-up...")
        recognizer_pool.warm_up_recognizers()
        time.sleep(4 * 60)  # Warm-up mỗi 4 phút

# Khởi chạy warm-up trong thread riêng
warm_up_thread = threading.Thread(target=auto_warm_up, daemon=True)
warm_up_thread.start()

# ========================================
# === ENDPOINTS CHÍNH ===
# ========================================
@app.route("/", methods=["GET"])
def index():
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET / from {request.remote_addr}")
    return render_template("STT.html")

@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    request_id = str(uuid.uuid4())
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] POST /api/transcribe from {request.remote_addr}")
    
    if "audio_data" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio_file = request.files["audio_data"]
    if not audio_file.filename.lower().endswith(".wav"):
        return jsonify({"error": "Invalid file type, .wav only"}), 400

    temp_path = os.path.join(TMP_DIR, f"{request_id}.wav")
    try:
        audio_file.save(temp_path)
        
        # Sử dụng recognizer từ pool
        recognizer = recognizer_pool.get_recognizer()
        try:
            with sr.AudioFile(temp_path) as source:
                audio_data = recognizer.record(source)
                try:
                    transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
                except sr.UnknownValueError:
                    transcript_text = ""
                except sr.RequestError as e:
                    return jsonify({"error": f"Speech API error: {e}"}), 500
        finally:
            recognizer_pool.return_recognizer(recognizer)
    except Exception as e:
        return jsonify({"error": f"File processing error: {e}"}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return jsonify({"transcript": transcript_text})

@app.route("/api/ping", methods=["GET"])
def ping():
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/ping from {request.remote_addr}")
    return jsonify({
        "status": "alive",
        "timestamp": time.time(),
        "recognizer_pool_size": len(recognizer_pool.pool)
    }), 200

# Vercel yêu cầu biến 'application' để deploy Flask
application = app

if __name__ == "__main__":
    app.run(debug=True)
