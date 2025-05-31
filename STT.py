# STT.py

import os
import uuid
from flask import Flask, render_template, request, jsonify
import speech_recognition as sr

# Khởi Flask, chỉ rõ thư mục chứa templates
app = Flask(__name__, template_folder="templates")

# Thư mục tạm để lưu file WAV (trên Vercel chỉ được ghi vào /tmp)
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def index():
    """
    GET /    → render trang HTML (ghi âm bằng JS, frontend).
    """
    return render_template("STT.html")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    """
    POST /transcribe    → nhận file WAV từ field 'audio_data',
                          chạy speech_recognition (Google Web Speech API),
                          trả JSON { "transcript": "..."} hoặc lỗi.
    """
    # 1. Kiểm tra field
    if "audio_data" not in request.files:
        return jsonify({"error": "Không tìm thấy field 'audio_data'"}), 400

    wav_file = request.files["audio_data"]
    if wav_file.filename == "":
        return jsonify({"error": "Tên file không hợp lệ"}), 400

    # 2. Chỉ chấp nhận .wav
    if not wav_file.filename.lower().endswith(".wav"):
        return jsonify({"error": "Chỉ chấp nhận file WAV (.wav)"}), 400

    # 3. Lưu tạm file
    unique_name = f"{uuid.uuid4().hex}.wav"
    tmp_path = os.path.join(TMP_DIR, unique_name)
    wav_file.save(tmp_path)

    # 4. Dùng speech_recognition để read và transcribe
    recognizer = sr.Recognizer()
    transcript_text = ""
    try:
        with sr.AudioFile(tmp_path) as source:
            audio_data = recognizer.record(source)  # đọc toàn bộ
        # Gọi Google Web Speech API (miễn phí, cần internet). language="vi-VN" để tiếng Việt
        transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
    except sr.UnknownValueError:
        # Không nhận dạng được
        transcript_text = ""
    except sr.RequestError as e:
        # Lỗi kết nối / quota / API
        os.remove(tmp_path)
        return jsonify({"error": f"Google Speech API error: {e}"}), 500
    finally:
        # Xóa file tạm
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # 5. Trả JSON
    return jsonify({"transcript": transcript_text})


# Lưu ý: không gọi app.run() ở đây, Vercel sẽ khởi function thay chúng ta.
