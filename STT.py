import os
import uuid
from flask import Flask, request, jsonify
import speech_recognition as sr

app = Flask(__name__)

# Giới hạn upload size (nếu muốn)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio_data" not in request.files:
        return jsonify({"transcript": ""}), 200

    wav_file = request.files["audio_data"]
    if wav_file.filename == "" or not wav_file.filename.lower().endswith(".wav"):
        return jsonify({"transcript": ""}), 200

    # Lưu file tạm
    unique_name = f"{uuid.uuid4().hex}.wav"
    tmp_path = os.path.join(TMP_DIR, unique_name)
    try:
        wav_file.save(tmp_path)
    except:
        return jsonify({"transcript": ""}), 200

    recognizer = sr.Recognizer()
    transcript_text = ""
    try:
        with sr.AudioFile(tmp_path) as source:
            audio_data = recognizer.record(source)
        transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
    except Exception:
        transcript_text = ""
    finally:
        try:
            os.remove(tmp_path)
        except:
            pass

    return jsonify({"transcript": transcript_text}), 200

# Lưu ý: Không gọi app.run() – Vercel sẽ tự động khởi.
