import os
import uuid
from flask import Flask, render_template, request, jsonify
import speech_recognition as sr

# Khởi tạo Flask, chỉ rõ thư mục chứa templates
app = Flask(__name__, template_folder="templates")

# Giới hạn kích thước file upload (ví dụ: 5 MB)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# Thư mục tạm để lưu file WAV (trên Vercel chỉ được ghi vào /tmp)
TMP_DIR = "/tmp"
os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def index():
    """
    GET / → render trang HTML (dùng Web Speech API demo)
    """
    return render_template("STT.html")


@app.route("/transcribe", methods=["POST"])
def transcribe():
    """
    POST /transcribe → nhận file WAV từ field 'audio_data',
                          chạy speech_recognition (Google Web Speech API),
                          trả JSON { "transcript": "..."} (luôn trả 200).
    """
    # 1. Kiểm tra field audio_data
    if "audio_data" not in request.files:
        return jsonify({"error": "Không tìm thấy field 'audio_data'"}), 400

    wav_file = request.files["audio_data"]
    if wav_file.filename == "":
        return jsonify({"error": "Tên file không hợp lệ"}), 400

    # 2. Chỉ chấp nhận .wav
    if not wav_file.filename.lower().endswith(".wav"):
        return jsonify({"error": "Chỉ chấp nhận file WAV (.wav)"}), 400

    # 3. Lưu tạm file vào /tmp
    unique_name = f"{uuid.uuid4().hex}.wav"
    tmp_path = os.path.join(TMP_DIR, unique_name)
    try:
        wav_file.save(tmp_path)
    except Exception as e:
        return jsonify({"error": f"Không lưu được file tạm: {e}"}), 500

    # 4. Dùng speech_recognition để read và transcribe
    recognizer = sr.Recognizer()
    transcript_text = ""
    try:
        with sr.AudioFile(tmp_path) as source:
            audio_data = recognizer.record(source)  # đọc toàn bộ tệp WAV
        # Gọi Google Web Speech API (language="vi-VN")
        transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
    except sr.UnknownValueError:
        # Khi Google không nhận dạng được --> trả transcript="" (không báo lỗi)
        transcript_text = ""
    except sr.RequestError as e:
        # Khi gặp lỗi kết nối/quota của Google API
        transcript_text = ""
    finally:
        # 5. Xóa file tạm (dù có lỗi hay không)
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # 6. Trả JSON (luôn 200) chứa trường "transcript" (có thể rỗng)
    return jsonify({"transcript": transcript_text})


# Lưu ý: Không gọi app.run() ở đây. Vercel sẽ tự khởi chính function
# Khi chạy locally (để test), bạn có thể bỏ comment 2 dòng dưới:
# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000)
