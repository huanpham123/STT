import os
import uuid
import time
import logging
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr

app = Flask(__name__, template_folder="templates")
app.logger.setLevel(logging.INFO)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

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
        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_path) as source:
            audio_data = recognizer.record(source)
            try:
                transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
            except sr.UnknownValueError:
                transcript_text = ""
            except sr.RequestError as e:
                return jsonify({"error": f"Speech API error: {e}"}), 500
    except Exception as e:
        return jsonify({"error": f"File processing error: {e}"}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return jsonify({"transcript": transcript_text})

@app.route("/api/ping", methods=["GET"])
def ping():
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/ping from {request.remote_addr}")
    return jsonify({"status": "alive", "timestamp": time.time()}), 200

# Vercel yêu cầu biến 'application' để deploy Flask
application = app

if __name__ == "__main__":
    app.run(debug=True)
