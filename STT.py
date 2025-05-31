import os
import uuid
from flask import Flask, render_template, request, jsonify
import speech_recognition as sr

# Khởi Flask, chỉ rõ template_folder là thư mục "templates"
app = Flask(__name__, template_folder="templates")

# Thư mục tạm để lưu file WAV (trong môi trường Serverless Vercel chỉ được ghi vào /tmp)
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def index():
    """
    Khi GET /, render file templates/STT.html.
    """
    return render_template("STT.html")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    """
    1) Nhận WAV blob từ field 'audio_data' (multipart/form-data),
    2) Lưu tạm vào /tmp/<uuid>.wav,
    3) Dùng speech_recognition để chuyển sang text (Google Web Speech API),
    4) Xóa file tạm,
    5) Trả JSON { "transcript": <chuỗi> } hoặc { "error": ... }.
    """
    # 1) Kiểm tra xem request có file 'audio_data' không
    if "audio_data" not in request.files:
        return jsonify({ "error": "Không tìm thấy field 'audio_data'" }), 400

    wav_file = request.files["audio_data"]
    if wav_file.filename == "":
        return jsonify({ "error": "Tên file không hợp lệ" }), 400

    # 2) Chỉ chấp nhận extension .wav
    if not wav_file.filename.lower().endswith(".wav"):
        return jsonify({ "error": "Chỉ chấp nhận file WAV (.wav)" }), 400

    # 3) Lưu tạm WAV vào /tmp với tên duy nhất
    unique_name = f"{uuid.uuid4().hex}.wav"
    tmp_path = os.path.join(TMP_DIR, unique_name)
    wav_file.save(tmp_path)

    # 4) Dùng speech_recognition để transcribe
    recognizer = sr.Recognizer()
    transcript_text = ""
    try:
        with sr.AudioFile(tmp_path) as source:
            audio_data = recognizer.record(source)  # đọc toàn bộ file
        # Gọi Google Web Speech API (miễn phí, yêu cầu mạng); language="vi-VN" để tiếng Việt
        transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
    except sr.UnknownValueError:
        # Khi không nhận dạng được
        transcript_text = ""
    except sr.RequestError as e:
        # Lỗi kết nối / API
        os.remove(tmp_path)
        return jsonify({ "error": f"Google Speech API error: {e}" }), 500
    finally:
        # Xóa file tạm (dù có lỗi hay không)
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # 5) Trả JSON
    return jsonify({ "transcript": transcript_text })


# Không cần điều kiện __main__ vì Vercel sẽ gọi module này như một Serverless Function.
