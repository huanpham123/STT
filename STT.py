import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
import speech_recognition as sr

app = Flask(__name__)

# Tạo thư mục tạm để lưu file WAV (Serverless chỉ cho ghi vào /tmp)
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def serve_index():
    """
    Trả về file index.html nằm ở thư mục gốc của project.
    Vì Vercel sẽ package code, __file__ là đường dẫn đến api/index.py,
    nên ta gọi send_from_directory về thư mục cha để lấy index.html
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return send_from_directory(root_dir, "STT.html")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    """
    Nhận WAV blob từ field 'audio_data' (multipart/form-data),
    lưu tạm vào /tmp/<uuid>.wav, dùng speech_recognition để
    chuyển sang text (Google Web Speech API), rồi xóa file tạm,
    trả JSON { "transcript": <chuỗi> } hoặc { "error": ... }.
    """
    if 'audio_data' not in request.files:
        return jsonify({ "error": "Không tìm thấy field 'audio_data'" }), 400

    wav_file = request.files['audio_data']
    if wav_file.filename == "":
        return jsonify({ "error": "Tên file không hợp lệ" }), 400

    # Kiểm tra extension .wav
    filename = wav_file.filename
    if not filename.lower().endswith(".wav"):
        return jsonify({ "error": "Chỉ chấp nhận file WAV (.wav)" }), 400

    # Tạo tên file tạm với uuid để tránh trùng lặp
    unique_name = f"{uuid.uuid4().hex}.wav"
    tmp_path = os.path.join(TMP_DIR, unique_name)
    wav_file.save(tmp_path)

    # Sử dụng speech_recognition để transcribe
    recognizer = sr.Recognizer()
    transcript_text = ""
    try:
        with sr.AudioFile(tmp_path) as source:
            audio_data = recognizer.record(source)  # đọc toàn bộ
        # Gọi Google Web Speech API (miễn phí, yêu cầu Internet)
        transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
    except sr.UnknownValueError:
        transcript_text = ""  # Không nhận dạng được
    except sr.RequestError as e:
        # Lỗi khi gọi API (mạng / Google không phản hồi)
        # Trả lỗi 500 kèm thông tin
        os.remove(tmp_path)
        return jsonify({ "error": f"Google Speech API error: {e}" }), 500
    finally:
        # Xóa file tạm
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return jsonify({ "transcript": transcript_text })

