import os
from flask import Flask, render_template, request, jsonify
import speech_recognition as sr
from werkzeug.utils import secure_filename

app = Flask(__name__)
# thư mục tạm để lưu file WAV upload
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# cho phép chỉ những file WAV
ALLOWED_EXTENSIONS = {'wav'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    # Trả về trang HTML chính (templates/index.html)
    return render_template("STT.html")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    """
    Nhận về một file WAV qua phần field 'audio_data' (multipart/form-data).
    Dùng speech_recognition để chuyển sang text, trả về JSON như: { "transcript": "..." }.
    """
    if 'audio_data' not in request.files:
        return jsonify({"error": "No audio_data field in request"}), 400

    wav_file = request.files['audio_data']
    if wav_file.filename == "" or not allowed_file(wav_file.filename):
        return jsonify({"error": "No selected file or invalid extension"}), 400

    # Lưu tạm WAV vào thư mục UPLOAD_FOLDER
    filename = secure_filename(wav_file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    wav_file.save(save_path)

    # Sử dụng speech_recognition để load và transcribe
    r = sr.Recognizer()
    try:
        with sr.AudioFile(save_path) as source:
            audio = r.record(source)  # đọc toàn bộ file
        # Sử dụng Google Web Speech API (miễn phí, yêu cầu Internet)
        text = r.recognize_google(audio, language="vi-VN")  # để tiếng Việt
    except sr.UnknownValueError:
        text = ""  # không nhận dạng được
    except sr.RequestError as e:
        # Có thể do lỗi mạng hoặc API không phản hồi
        return jsonify({"error": f"API request failed: {e}"}), 500
    finally:
        # Xóa file WAV tạm
        try:
            os.remove(save_path)
        except OSError:
            pass

    return jsonify({"transcript": text})

if __name__ == "__main__":
    # Chạy server dev, port 5000, debug off
    app.run(host="0.0.0.0", port=5000)
