import os
import uuid
import time
import logging
from flask import Flask, request, jsonify, render_template # Đã thêm render_template
import speech_recognition as sr
import threading
import wave
import io

# --- Khởi tạo Flask App ---
app = Flask(__name__)
app.logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')

# --- Cấu hình ---
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Giới hạn upload 5MB
TMP_DIR = "/tmp"  # Vercel cho phép ghi vào /tmp
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR, exist_ok=True)

# --- File WAV im lặng để Warm-up Recognizer ---
SILENT_WAV_PATH = os.path.join(TMP_DIR, "silent_warmup_stt.wav")

def create_silent_wav(path, duration=0.1, sample_rate=16000):
    try:
        n_channels = 1
        sampwidth = 2  # 16-bit
        n_frames = int(duration * sample_rate)
        comp_type = "NONE"
        comp_name = "not compressed"
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(sample_rate)
            wf.setnframes(n_frames)
            wf.setcomptype(comp_type, comp_name)
            wf.writeframes(b'\x00\x00' * n_frames)
        app.logger.info(f"File WAV im lặng đã tạo tại: {path}")
        return True
    except Exception as e:
        app.logger.error(f"Không thể tạo file WAV im lặng: {e}", exc_info=True)
        return False

if not create_silent_wav(SILENT_WAV_PATH):
    app.logger.warning("Không thể tạo file WAV im lặng. Việc warm-up recognizer có thể bị ảnh hưởng.")

# --- Pool cho Recognizer ---
class RecognizerPool:
    def __init__(self, pool_size=2, max_pool_size=5): # Giảm size cho môi trường resource hạn chế
        self.initial_pool_size = pool_size
        self.max_pool_size = max_pool_size
        self.pool = []
        self.lock = threading.Lock()
        self._initialize_pool()
        self.warm_up_all_recognizers_in_pool()

    def _initialize_pool(self):
        with self.lock:
            self.pool = [sr.Recognizer() for _ in range(self.initial_pool_size)]
        app.logger.info(f"RecognizerPool đã khởi tạo với {self.initial_pool_size} instance.")

    def _warm_up_single_recognizer(self, recognizer):
        if not os.path.exists(SILENT_WAV_PATH):
            try: # Thao tác nhẹ để kích hoạt
                recognizer.energy_threshold += 0
            except Exception as e_benign:
                 app.logger.debug(f"Benign operation for warm-up failed for {id(recognizer)}: {e_benign}")
            return
        try:
            with sr.AudioFile(SILENT_WAV_PATH) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.05)
            # app.logger.debug(f"Instance recognizer {id(recognizer)} đã được warm-up.")
        except FileNotFoundError:
            app.logger.error(f"File WAV warm-up không tìm thấy: {SILENT_WAV_PATH}.")
        except sr.WaitTimeoutError:
            app.logger.warning(f"Lỗi WaitTimeoutError khi warm-up recognizer: {id(recognizer)}")
        except Exception as e:
            app.logger.error(f"Lỗi khi warm-up instance recognizer {id(recognizer)}: {e}", exc_info=False)

    def warm_up_all_recognizers_in_pool(self):
        app.logger.info("Bắt đầu quá trình warm-up recognizer pool...")
        threads = []
        current_recognizers = []
        with self.lock:
            current_recognizers = list(self.pool) # Tạo bản sao để duyệt

        for r_instance in current_recognizers:
            thread = threading.Thread(target=self._warm_up_single_recognizer, args=(r_instance,), name=f"WarmUpThread-{id(r_instance)}")
            thread.daemon = True # Cho phép thoát kể cả khi thread đang chạy
            thread.start()
            threads.append(thread)
        
        for thread in threads:
            thread.join(timeout=5.0)
        app.logger.info(f"Hoàn tất quá trình warm-up recognizer pool. Số thread đang hoạt động: {threading.active_count()}")

    def get_recognizer(self):
        with self.lock:
            if self.pool:
                return self.pool.pop(0)
            else:
                app.logger.info("Pool rỗng, tạo recognizer mới.")
                new_recognizer = sr.Recognizer()
                # Cân nhắc warm-up recognizer mới này ngay lập tức (có thể làm tăng độ trễ chút ít)
                # threading.Thread(target=self._warm_up_single_recognizer, args=(new_recognizer,)).start()
                return new_recognizer
    
    def return_recognizer(self, recognizer):
        with self.lock:
            if len(self.pool) < self.max_pool_size:
                self.pool.append(recognizer)

recognizer_pool = RecognizerPool()

# --- Biến cho việc warm-up thông qua Ping ---
LAST_PING_TRIGGERED_WARM_UP_TIME = 0
MIN_INTERVAL_BETWEEN_PING_WARM_UPS_SECONDS = 4 * 60  # 4 phút
PING_WARM_UP_THREAD = None

# --- Các Flask Route ---
@app.route("/", methods=["GET"])
def index_route():
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET / từ {request.remote_addr}")
    return render_template("STT.html") # Render file HTML

@app.route("/api/status", methods=["GET"]) # Đổi tên route "/" thành "/api/status" cho rõ ràng hơn
def status_route():
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/status từ {request.remote_addr}")
    current_pool_size = 0
    with recognizer_pool.lock:
        current_pool_size = len(recognizer_pool.pool)
    return jsonify({
        "message": "STT Server is running.",
        "status": "healthy",
        "timestamp": time.time(),
        "recognizer_pool_size": current_pool_size,
        "active_threads": threading.active_count()
    }), 200

@app.route("/api/ping", methods=["GET"])
def ping_route():
    global LAST_PING_TRIGGERED_WARM_UP_TIME, PING_WARM_UP_THREAD
    ping_type = request.headers.get('X-Ping-Type', 'Unknown') # Cho phép client tự định danh loại ping
    
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/ping từ {request.remote_addr} (Loại: {ping_type})")
    
    current_time = time.time()
    # Kiểm tra và kích hoạt warm-up nếu cần và không có thread warm-up nào đang chạy
    if (PING_WARM_UP_THREAD is None or not PING_WARM_UP_THREAD.is_alive()) and \
       (current_time - LAST_PING_TRIGGERED_WARM_UP_TIME > MIN_INTERVAL_BETWEEN_PING_WARM_UPS_SECONDS):
        app.logger.info(f"🔥 Triggering recognizer pool warm-up via ping...")
        PING_WARM_UP_THREAD = threading.Thread(target=recognizer_pool.warm_up_all_recognizers_in_pool, name="PingWarmUpThread")
        PING_WARM_UP_THREAD.daemon = True
        PING_WARM_UP_THREAD.start()
        LAST_PING_TRIGGERED_WARM_UP_TIME = current_time
    # else:
    #     app.logger.debug(f"Skipping warm-up: Thread running or too recent. Last warm-up: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(LAST_PING_TRIGGERED_WARM_UP_TIME))}")

    current_pool_size = 0
    with recognizer_pool.lock:
        current_pool_size = len(recognizer_pool.pool)

    return jsonify({
        "status": "alive",
        "timestamp": current_time,
        "recognizer_pool_size": current_pool_size,
        "message": "STT server đang hoạt động và sẵn sàng.",
        "active_threads": threading.active_count()
    }), 200

@app.route("/api/transcribe", methods=["POST"])
def transcribe_route():
    request_id = str(uuid.uuid4())
    process_start_time = time.perf_counter()
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] POST /api/transcribe từ {request.remote_addr}")

    if "audio_data" not in request.files:
        app.logger.warning(f"[ReqID:{request_id}] Thiếu file audio_data.")
        return jsonify({"error": "Missing audio file", "transcript": ""}), 400

    audio_file = request.files["audio_data"]

    if not audio_file.filename or not audio_file.filename.lower().endswith(".wav"):
        app.logger.warning(f"[ReqID:{request_id}] Loại file không hợp lệ: {audio_file.filename}")
        return jsonify({"error": "Invalid file type, .wav only", "transcript": ""}), 400

    temp_filename = f"{request_id}.wav"
    temp_path = os.path.join(TMP_DIR, temp_filename)
    
    transcript_text = ""
    error_message_detail = None # Chi tiết lỗi nếu có
    final_status_code = 200

    try:
        audio_file.save(temp_path)
        # app.logger.info(f"[ReqID:{request_id}] File audio đã lưu tại {temp_path}")

        recognizer_instance = recognizer_pool.get_recognizer()
        # app.logger.info(f"[ReqID:{request_id}] Đã lấy recognizer {id(recognizer_instance)}.")
        
        try:
            with sr.AudioFile(temp_path) as source:
                # app.logger.info(f"[ReqID:{request_id}] Đang record từ file...")
                audio_data = recognizer_instance.record(source)
                # app.logger.info(f"[ReqID:{request_id}] Đã record. Bắt đầu nhận dạng...")
            
                try:
                    transcript_text = recognizer_instance.recognize_google(audio_data, language="vi-VN")
                    app.logger.info(f"[ReqID:{request_id}] Nhận dạng thành công: '{transcript_text}'")
                except sr.UnknownValueError:
                    app.logger.warning(f"[ReqID:{request_id}] Google SR không thể hiểu audio.")
                    error_message_detail = "Không thể nhận dạng giọng nói từ audio."
                    # transcript_text để trống hoặc thông báo cụ thể
                except sr.RequestError as e:
                    app.logger.error(f"[ReqID:{request_id}] Lỗi API SR: {e}", exc_info=True)
                    error_message_detail = f"Lỗi kết nối tới dịch vụ Speech Recognition: {e}"
                    final_status_code = 503 # Service Unavailable
                except Exception as e_rec:
                    app.logger.error(f"[ReqID:{request_id}] Lỗi nhận dạng không xác định: {e_rec}", exc_info=True)
                    error_message_detail = "Lỗi máy chủ không xác định trong quá trình nhận dạng."
                    final_status_code = 500
        finally:
            recognizer_pool.return_recognizer(recognizer_instance)
            # app.logger.info(f"[ReqID:{request_id}] Đã trả recognizer {id(recognizer_instance)}.")

    except Exception as e_general:
        app.logger.error(f"[ReqID:{request_id}] Lỗi xử lý file: {e_general}", exc_info=True)
        error_message_detail = f"Lỗi máy chủ khi xử lý file audio: {str(e_general)}"
        final_status_code = 500
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                # app.logger.info(f"[ReqID:{request_id}] File tạm {temp_path} đã xóa.")
            except Exception as e_remove:
                app.logger.error(f"[ReqID:{request_id}] Lỗi xóa file tạm {temp_path}: {e_remove}", exc_info=True)
        
        process_end_time = time.perf_counter()
        app.logger.info(f"[ReqID:{request_id}] Xử lý trong {process_end_time - process_start_time:.4f}s. Status: {final_status_code}")

    if final_status_code == 200 and error_message_detail is None: # Thành công và không có lỗi cụ thể nào được ghi nhận
        return jsonify({"transcript": transcript_text, "error": None}), 200
    else: # Có lỗi xảy ra
        effective_error = error_message_detail if error_message_detail else "Lỗi máy chủ STT không xác định."
        return jsonify({"error": effective_error, "transcript": ""}), final_status_code

# --- Main Execution (cho Vercel) ---
application = app # Vercel tìm biến 'application' hoặc 'app'

# Block if __name__ == "__main__": chỉ dùng cho phát triển local
# Vercel sẽ không chạy block này.
if __name__ == "__main__":
    app.logger.info("Khởi chạy Flask development server (local)...")
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5002)), threaded=True)
