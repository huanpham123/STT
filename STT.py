import os
import uuid
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr

app = Flask(__name__, template_folder="templates")

# Cấu hình
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB
TMP_DIR = "/tmp" # Vercel hỗ trợ thư mục /tmp
os.makedirs(TMP_DIR, exist_ok=True)

@app.route("/", methods=["GET"])
def index():
    """Trang chủ hiển thị giao diện Web Speech API (dùng API của trình duyệt)"""
    return render_template("STT.html")

@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """API endpoint cho nhận dạng giọng nói từ ESP32 hoặc client khác"""
    if "audio_data" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    audio_file = request.files["audio_data"]
    
    # Kiểm tra tên file có ".wav" không (dù ESP32 gửi Content-Type là audio/wav)
    # an toàn hơn nếu kiểm tra cả Content-Type
    if not audio_file.filename or not audio_file.filename.lower().endswith(".wav"):
        # Hoặc bạn có thể kiểm tra audio_file.content_type == 'audio/wav'
        return jsonify({"error": "Invalid file type, expecting .wav"}), 400

    # Lưu file tạm
    temp_filename = f"{uuid.uuid4()}.wav"
    temp_path = os.path.join(TMP_DIR, temp_filename)
    
    try:
        audio_file.save(temp_path)
        print(f"Audio file saved to: {temp_path}")

        # Nhận dạng giọng nói
        recognizer = sr.Recognizer()
        transcript = ""
        
        with sr.AudioFile(temp_path) as source:
            audio_data = recognizer.record(source) # Đọc toàn bộ file audio
            print("Audio data recorded from file.")
            try:
                # Sử dụng Google Web Speech API để nhận dạng
                transcript = recognizer.recognize_google(audio_data, language="vi-VN")
                print(f"Transcript: {transcript}")
            except sr.UnknownValueError:
                print("Google Speech Recognition could not understand audio")
                transcript = "" # Hoặc thông báo lỗi cụ thể
            except sr.RequestError as e:
                print(f"Could not request results from Google Speech Recognition service; {e}")
                return jsonify({"error": f"Speech recognition service error: {e}"}), 500
            except Exception as e_rec:
                 print(f"Error during recognition: {str(e_rec)}")
                 return jsonify({"error": f"Recognition processing error: {str(e_Rec)}"}), 500

    except Exception as e_save:
        print(f"Error saving or processing file: {str(e_save)}")
        return jsonify({"error": f"File processing error: {str(e_save)}"}), 500
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                print(f"Temporary file {temp_path} removed.")
            except Exception as e_del:
                print(f"Error deleting temporary file {temp_path}: {str(e_del)}")


    return jsonify({"transcript": transcript})

# Vercel yêu cầu biến application
application = app

# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=5000) # Để chạy thử nghiệm cục bộ
