import os
import uuid
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr
import time
import logging

# --- Cấu hình Flask App và Logging ---
app = Flask(__name__, template_folder="templates") # Đảm bảo thư mục templates đúng

# Cấu hình logging cơ bản của Flask
# Log sẽ xuất hiện trong Vercel Runtime Logs
app.logger.setLevel(logging.INFO) # Có thể đặt DEBUG để xem chi tiết hơn

# --- Cấu hình chung ---
# Giới hạn kích thước nội dung request tối đa là 5MB
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  
# Thư mục tạm trên Vercel (chỉ có /tmp là có thể ghi)
TMP_DIR = "/tmp" 
# Đảm bảo thư mục tạm tồn tại
os.makedirs(TMP_DIR, exist_ok=True)


# --- Routes ---
@app.route("/", methods=["GET"])
def index():
    """Trang chủ hiển thị giao diện Web Speech API (dùng API của trình duyệt)"""
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET request to / from {request.remote_addr}")
    return render_template("STT.html") # Tên file HTML của bạn

@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """API endpoint cho nhận dạng giọng nói từ ESP32 hoặc client khác"""
    request_received_time = time.time()
    request_id = str(uuid.uuid4()) # Tạo ID duy nhất cho mỗi request để dễ theo dõi log
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] POST /api/transcribe from {request.remote_addr}")

    if "audio_data" not in request.files:
        app.logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Missing 'audio_data' in request files.")
        return jsonify({"error": "Missing audio file"}), 400

    audio_file = request.files["audio_data"]
    
    if not audio_file.filename or not audio_file.filename.lower().endswith(".wav"):
        app.logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Invalid file type: {audio_file.filename}. Expecting .wav.")
        # Bạn cũng có thể kiểm tra audio_file.content_type == 'audio/wav'
        return jsonify({"error": "Invalid file type, expecting .wav"}), 400

    # Tạo tên file tạm duy nhất trong thư mục /tmp
    temp_filename = f"{request_id}.wav" # Sử dụng request_id để tên file dễ liên kết với log
    temp_path = os.path.join(TMP_DIR, temp_filename)
    
    try:
        save_start_time = time.time()
        audio_file.save(temp_path)
        file_size = os.path.getsize(temp_path)
        app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Audio file saved to: {temp_path}. Size: {file_size} bytes. Save time: {time.time() - save_start_time:.2f}s")

        # Nhận dạng giọng nói
        recognizer = sr.Recognizer()
        transcript_text = "" # Đổi tên biến để tránh trùng với tên hàm
        
        with sr.AudioFile(temp_path) as source:
            record_start_time = time.time()
            # Đọc toàn bộ file audio
            audio_data = recognizer.record(source) 
            app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Audio data loaded from file. Load time: {time.time() - record_start_time:.2f}s")
            
            try:
                recognize_start_time = time.time()
                # Sử dụng Google Web Speech API để nhận dạng (mặc định của speech_recognition)
                transcript_text = recognizer.recognize_google(audio_data, language="vi-VN")
                app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Transcript: '{transcript_text}'. Recognition time: {time.time() - recognize_start_time:.2f}s")
            except sr.UnknownValueError:
                app.logger.warning(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Google Speech Recognition could not understand audio.")
                transcript_text = "" # Hoặc thông báo lỗi cụ thể cho client
            except sr.RequestError as e:
                app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Google Speech Recognition service error; {e}")
                return jsonify({"error": f"Speech recognition service error: {e}"}), 500
            except Exception as e_rec: # Sửa lỗi typo e_Rec thành e_rec
                app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Error during speech recognition processing: {str(e_rec)}")
                return jsonify({"error": f"Recognition processing error: {str(e_rec)}"}), 500

    except Exception as e_file_processing:
        app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Error saving or processing audio file: {str(e_file_processing)}")
        return jsonify({"error": f"File processing error: {str(e_file_processing)}"}), 500
    finally:
        # Luôn cố gắng xóa file tạm sau khi xử lý
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Temporary file {temp_path} removed.")
            except Exception as e_del:
                app.logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Error deleting temporary file {temp_path}: {str(e_del)}")

    total_processing_time = time.time() - request_received_time
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID: {request_id}] Request to /api/transcribe finished. Total processing time: {total_processing_time:.2f}s")
    return jsonify({"transcript": transcript_text})

@app.route("/api/ping", methods=["GET"])
def ping():
    """Endpoint đơn giản để kiểm tra server hoặc "warm-up" function trên Vercel"""
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/ping (warm-up/status check)")
    return jsonify({"status": "alive", "timestamp": time.time()}), 200

# Vercel yêu cầu một biến tên là 'application' hoặc 'app' để chạy ứng dụng Flask.
# Nếu tên file của bạn là app.py, Vercel sẽ tự tìm biến app.
# Nếu tên file khác (ví dụ STT.py), bạn cần đảm bảo có dòng này:
application = app

if __name__ == '__main__':
    app.run(debug=True)
