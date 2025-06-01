import os
import uuid
import time
import logging
from flask import Flask, request, jsonify, render_template
import speech_recognition as sr
import threading
import wave  # Để tạo file WAV im lặng
import io    # Để làm việc với file WAV trong bộ nhớ (nếu cần)

# --- Khởi tạo Flask App ---
app = Flask(__name__, template_folder="templates")
app.logger.setLevel(logging.INFO) # Sử dụng logger của Flask
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')


# --- Cấu hình ---
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # Giới hạn upload 5MB
TMP_DIR = "/tmp"  # Vercel cho phép ghi vào /tmp
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR, exist_ok=True)

# --- File WAV im lặng để Warm-up Recognizer ---
SILENT_WAV_PATH = os.path.join(TMP_DIR, "silent_warmup_stt.wav")

def create_silent_wav(path, duration=0.1, sample_rate=16000):
    """Tạo một file WAV im lặng ngắn."""
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
            wf.writeframes(b'\x00\x00' * n_frames) # Dữ liệu im lặng (zero bytes)
        app.logger.info(f"File WAV im lặng đã được tạo tại: {path}")
        return True
    except Exception as e:
        app.logger.error(f"Không thể tạo file WAV im lặng: {e}", exc_info=True)
        return False

# Tạo file WAV im lặng khi server khởi động
# Đối với Vercel, /tmp là ephemeral, nên việc tạo khi khởi động là cần thiết.
if not create_silent_wav(SILENT_WAV_PATH):
    app.logger.warning("Không thể tạo file WAV im lặng. Việc warm-up recognizer có thể bị ảnh hưởng.")

# --- Pool cho Recognizer ---
class RecognizerPool:
    def __init__(self, pool_size=3, max_pool_size=10):
        self.initial_pool_size = pool_size
        self.max_pool_size = max_pool_size
        self.pool = []
        self.lock = threading.Lock() # Lock để đảm bảo thread-safe
        self._initialize_pool()
        self.warm_up_all_recognizers_in_pool() # Warm-up ngay sau khi khởi tạo

    def _initialize_pool(self):
        """Khởi tạo các đối tượng recognizer trong pool."""
        with self.lock:
            # Đảm bảo pool trống trước khi khởi tạo lại (nếu cần)
            self.pool = [sr.Recognizer() for _ in range(self.initial_pool_size)]
        app.logger.info(f"RecognizerPool đã khởi tạo với {self.initial_pool_size} instance.")

    def _warm_up_single_recognizer(self, recognizer):
        """Warm-up một instance recognizer cụ thể."""
        if not os.path.exists(SILENT_WAV_PATH):
            try: # Thử một thao tác không ảnh hưởng nhiều để kích hoạt recognizer
                recognizer.energy_threshold = recognizer.energy_threshold + 0 
            except Exception as e_benign:
                 app.logger.debug(f"Benign operation for warm-up failed for {id(recognizer)}: {e_benign}")
            return

        try:
            with sr.AudioFile(SILENT_WAV_PATH) as source:
                # Điều chỉnh nhanh cho tiếng ồn xung quanh để "chạm" vào các thành phần của recognizer
                recognizer.adjust_for_ambient_noise(source, duration=0.05)
            # app.logger.debug(f"Instance recognizer {id(recognizer)} đã được warm-up.")
        except FileNotFoundError:
            app.logger.error(f"File WAV warm-up không tìm thấy: {SILENT_WAV_PATH}. Warm-up có thể không hiệu quả.")
        except sr.WaitTimeoutError:
             app.logger.warning(f"Lỗi WaitTimeoutError trong quá trình warm-up recognizer: {id(recognizer)}")
        except Exception as e:
            app.logger.error(f"Lỗi khi warm-up instance recognizer {id(recognizer)}: {e}", exc_info=False)


    def warm_up_all_recognizers_in_pool(self):
        """Warm-up tất cả recognizer trong pool (sử dụng thread)."""
        app.logger.info("Bắt đầu quá trình warm-up recognizer pool...")
        threads = []
        
        with self.lock: # Sao chép pool để tránh thay đổi trong lúc duyệt
            current_recognizers = list(self.pool)

        for r_instance in current_recognizers:
            thread = threading.Thread(target=self._warm_up_single_recognizer, args=(r_instance,), name=f"WarmUpThread-{id(r_instance)}")
            thread.start()
            threads.append(thread)
        
        for thread in threads:
            thread.join(timeout=5.0) # Chờ thread hoàn thành với timeout
        app.logger.info(f"Hoàn tất quá trình warm-up recognizer pool. Số thread đang hoạt động: {threading.active_count()}")

    def get_recognizer(self):
        """Lấy một recognizer từ pool hoặc tạo mới nếu pool rỗng."""
        with self.lock:
            if self.pool:
                # app.logger.debug("Lấy recognizer từ pool.")
                return self.pool.pop(0) # Lấy từ đầu danh sách (FIFO-like)
            else:
                app.logger.info("Pool rỗng, tạo recognizer mới.")
                new_recognizer = sr.Recognizer()
                # Tùy chọn: warm-up recognizer mới này ngay lập tức
                # self._warm_up_single_recognizer(new_recognizer) # Có thể làm tăng độ trễ ở đây
                return new_recognizer
    
    def return_recognizer(self, recognizer):
        """Trả recognizer về pool nếu chưa đầy."""
        with self.lock:
            if len(self.pool) < self.max_pool_size:
                # app.logger.debug("Trả recognizer về pool.")
                self.pool.append(recognizer) # Thêm vào cuối danh sách
            # else:
                # app.logger.debug("Pool đã đầy, loại bỏ recognizer.")

# Khởi tạo pool
recognizer_pool = RecognizerPool()

# --- Thread Tự động Warm-up Định kỳ ---
# Lưu ý: Hiệu quả trên Vercel phụ thuộc vào lifecycle của instance.
# Giúp giữ recognizer "ấm" nếu instance Vercel được giữ sống bởi ping bên ngoài.
AUTO_WARM_UP_INTERVAL_SECONDS = 4 * 60  # 4 phút

def auto_warm_up_task():
    app.logger.info(f"Thread tự động warm-up đã bắt đầu. Chu kỳ: {AUTO_WARM_UP_INTERVAL_SECONDS} giây.")
    while True:
        time.sleep(AUTO_WARM_UP_INTERVAL_SECONDS)
        app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🔥 Thực hiện warm-up recognizer pool định kỳ...")
        recognizer_pool.warm_up_all_recognizers_in_pool()

# Chỉ khởi chạy thread nếu không phải môi trường Vercel (nơi thread dài hạn không đảm bảo)
# Hoặc nếu bạn muốn thử nghiệm nó trên Vercel.
# Một cách tiếp cận thân thiện hơn với serverless là kích hoạt warm-up từ /api/ping nếu đã lâu chưa warm-up.
IS_VERCEL_ENV = os.environ.get("VERCEL") == "1"
if not IS_VERCEL_ENV: 
    warm_up_bg_thread = threading.Thread(target=auto_warm_up_task, daemon=True, name="AutoWarmUpBGThread")
    warm_up_bg_thread.start()
else:
    app.logger.info("Đang chạy trên Vercel, thread warm-up nền dài hạn bị tắt. Warm-up khi khởi tạo và có thể qua ping.")

# --- Các Flask Route ---
@app.route("/", methods=["GET"])
def index_route():
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET / từ {request.remote_addr}")
    return render_template("STT.html") # Đảm bảo STT.html nằm trong thư mục 'templates'

@app.route("/api/ping", methods=["GET"])
def ping_route():
    ping_type = "Unknown"
    if request.headers.get('X-Health-Check') == 'true':
        ping_type = "Health-Check (Client UI)"
    elif request.headers.get('X-Keep-Alive') == 'true':
        ping_type = "Keep-Alive (Client UI)"
    # Thêm header nếu ESP32 gửi ping (ví dụ: 'X-ESP32-Ping': 'true')
    elif request.headers.get('X-ESP32-Ping') == 'true':
        ping_type = "Keep-Alive (ESP32)"
    
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GET /api/ping từ {request.remote_addr} (Loại: {ping_type})")
    
    current_pool_size = 0
    with recognizer_pool.lock: # Truy cập pool size một cách an toàn
        current_pool_size = len(recognizer_pool.pool)

    return jsonify({
        "status": "alive",
        "timestamp": time.time(),
        "recognizer_pool_size": current_pool_size,
        "message": "STT server đang hoạt động và sẵn sàng.",
        "active_threads": threading.active_count() # Để debug việc sử dụng thread
    }), 200

@app.route("/api/transcribe", methods=["POST"])
def transcribe_route():
    request_id = str(uuid.uuid4()) # ID duy nhất cho mỗi request
    process_start_time = time.perf_counter() # Đo thời gian xử lý
    app.logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [ReqID:{request_id}] POST /api/transcribe từ {request.remote_addr}")

    if "audio_data" not in request.files:
        app.logger.warning(f"[ReqID:{request_id}] Thiếu file audio_data trong request.")
        return jsonify({"error": "Missing audio file", "transcript": ""}), 400

    audio_file = request.files["audio_data"]

    if not audio_file.filename or not audio_file.filename.lower().endswith(".wav"):
        app.logger.warning(f"[ReqID:{request_id}] Loại file không hợp lệ hoặc không có tên file. Nhận: {audio_file.filename}")
        return jsonify({"error": "Invalid file type, .wav only", "transcript": ""}), 400

    # Tên file tạm thời dựa trên request_id để đảm bảo tính duy nhất
    temp_filename = f"{request_id}.wav"
    temp_path = os.path.join(TMP_DIR, temp_filename)
    
    transcript_text = ""
    final_status_code = 200 # Mặc định là thành công

    try:
        audio_file.save(temp_path)
        app.logger.info(f"[ReqID:{request_id}] File audio đã lưu tại {temp_path}")

        recognizer_instance = recognizer_pool.get_recognizer()
        app.logger.info(f"[ReqID:{request_id}] Đã lấy instance recognizer {id(recognizer_instance)} từ pool.")
        
        try:
            with sr.AudioFile(temp_path) as source:
                app.logger.info(f"[ReqID:{request_id}] Đang ghi âm (record) từ file audio...")
                # Tùy chọn: recognizer_instance.adjust_for_ambient_noise(source, duration=0.2)
                audio_data = recognizer_instance.record(source)
                app.logger.info(f"[ReqID:{request_id}] Đã record audio. Bắt đầu nhận dạng...")
            
            try:
                transcript_text = recognizer_instance.recognize_google(audio_data, language="vi-VN")
                app.logger.info(f"[ReqID:{request_id}] Nhận dạng thành công: '{transcript_text}'")
            except sr.UnknownValueError:
                app.logger.warning(f"[ReqID:{request_id}] Google Speech Recognition không thể hiểu audio.")
                transcript_text = "" # Hoặc "[Không thể nhận dạng]"
            except sr.RequestError as e:
                app.logger.error(f"[ReqID:{request_id}] Lỗi API Speech Recognition: {e}", exc_info=True)
                transcript_text = f"[Lỗi kết nối API Speech: {e}]"
                final_status_code = 503 # Service Unavailable
            except Exception as e_rec:
                app.logger.error(f"[ReqID:{request_id}] Lỗi không xác định trong quá trình nhận dạng: {e_rec}", exc_info=True)
                transcript_text = "[Lỗi xử lý giọng nói không xác định]"
                final_status_code = 500
        finally:
            recognizer_pool.return_recognizer(recognizer_instance)
            app.logger.info(f"[ReqID:{request_id}] Đã trả instance recognizer {id(recognizer_instance)} về pool.")

    except Exception as e_general:
        app.logger.error(f"[ReqID:{request_id}] Lỗi xử lý file hoặc lỗi chung: {e_general}", exc_info=True)
        final_status_code = 500 # Internal Server Error
        # Đảm bảo trả về JSON error object
        return jsonify({"error": f"Lỗi server khi xử lý file: {str(e_general)}", "transcript": ""}), final_status_code

    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                app.logger.info(f"[ReqID:{request_id}] File tạm {temp_path} đã được xóa.")
            except Exception as e_remove:
                app.logger.error(f"[ReqID:{request_id}] Lỗi khi xóa file tạm {temp_path}: {e_remove}", exc_info=True)
        
        process_end_time = time.perf_counter()
        app.logger.info(f"[ReqID:{request_id}] Request được xử lý trong {process_end_time - process_start_time:.4f} giây. Status: {final_status_code}")

    if final_status_code != 200:
         # Nếu có lỗi đã được ghi nhận trong quá trình nhận dạng, trả về thông tin lỗi đó
        return jsonify({"error": transcript_text if transcript_text.startswith("[Lỗi") else "Lỗi máy chủ STT không xác định", "transcript": ""}), final_status_code
    else:
        return jsonify({"transcript": transcript_text, "error": None}), 200


# --- Main Execution (cho Vercel và local) ---
application = app  # Vercel tìm biến 'application' hoặc 'app'

if __name__ == "__main__":
    # Block này chạy khi thực thi script trực tiếp (ví dụ: phát triển local)
    # Vercel không dùng block này để serve, nó dùng callable 'application'.
    app.logger.info("Khởi chạy Flask development server...")
    # Đảm bảo thư mục 'templates' với file STT.html tồn tại khi chạy local.
    # Thread warm-up sẽ khởi chạy nếu không phải môi trường Vercel.
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5002)), threaded=True)
    # threaded=True cho phép xử lý nhiều request đồng thời khi test local.
