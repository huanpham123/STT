import os
import uuid
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr

app = Flask(__name__, template_folder="templates")

# Cấu hình
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def index():
    """Trang chủ hiển thị giao diện Web Speech API"""
    return render_template("STT.html")

@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """API endpoint cho nhận dạng giọng nói"""
    if "audio_data" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio_file = request.files["audio_data"]
    if not audio_file.filename.lower().endswith(".wav"):
        return jsonify({"error": "Invalid file type"}), 400

    # Lưu file tạm
    temp_path = os.path.join(TMP_DIR, f"{uuid.uuid4()}.wav")
    audio_file.save(temp_path)

    # Nhận dạng giọng nói
    recognizer = sr.Recognizer()
    transcript = ""
    
    try:
        with sr.AudioFile(temp_path) as source:
            audio_data = recognizer.record(source)
            transcript = recognizer.recognize_google(audio_data, language="vi-VN")
    except sr.UnknownValueError:
        transcript = ""
    except Exception as e:
        print(f"Error: {str(e)}")
        transcript = ""
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return jsonify({"transcript": transcript})

# Vercel yêu cầu biến application
application = app
