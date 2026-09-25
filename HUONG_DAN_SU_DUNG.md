# HƯỚNG DẪN SỬ DỤNG CHI TIẾT PYVIDEOTRANS (TỪ A ĐẾN Z)

Bộ tài liệu hướng dẫn đầy đủ cách vận hành phần mềm **pyVideoTrans** - Công cụ mở nguồn chuyển đổi ngôn ngữ Video, nhận dạng giọng nói (ASR/STT), dịch thuật phụ đề bằng AI (LLM), lồng tiếng tự động (TTS) và đồng bộ âm thanh video.

---

## 📌 1. GIỚI THIỆU TỔNG QUAN

**pyVideoTrans** là ứng dụng chuyên sâu cho quy trình xử lý video đa ngôn ngữ với các tính năng vượt trội:

- **Dịch Video tự động toàn trình (Video Translation)**: Tự động Nhận dạng giọng nói (ASR) ➔ Dịch phụ đề ➔ Lồng tiếng AI (TTS) ➔ Tổng hợp Video hoàn chỉnh.
- **Nhận dạng giọng nói (Speech to Text - STT)**: Xuất âm thanh/video ra file phụ đề chuẩn `.srt`, hỗ trợ phân biệt người nói (**Speaker Diarization**) để chia nhân vật.
- **Dịch thuật phụ đề (Subtitle Translation)**: Hỗ trợ các mô hình AI LLM tiên tiến (DeepSeek, ChatGPT, Gemini, Claude, Ollama offline) và máy dịch truyền thống.
- **Lồng tiếng đa nhân vật (Multi-Role AI Dubbing)**: Gán từng giọng đọc AI riêng cho từng nhân vật xuất hiện trong video.
- **Nhái giọng nói AI (Voice Cloning)**: Tích hợp các mô hình F5-TTS, CosyVoice, GPT-SoVITS để sao chép giọng mẫu từ audio ngắn.
- **Bộ công cụ phụ trợ (Toolkit)**: Tách lời thoại & nhạc nền (Vocal Separation), ghép phụ đề cứng/mềm, chỉnh sửa dòng thời gian âm thanh.

---

## 🚀 2. CÁCH KHỞI CHẠY ỨNG DỤNG

Dự án pyVideoTrans hỗ trợ 3 giao diện làm việc chính tùy theo nhu cầu sử dụng:

### 2.1. Giao diện Đồ họa Máy tính (GUI Desktop - Khuyên dùng)
Giao diện trực quan đầy đủ nhất, hỗ trợ tạm dừng và hiệu chỉnh thủ công ở từng bước dịch.
- **Lệnh khởi chạy**:
  ```bash
  uv run sp.py
  ```

### 2.2. Giao diện Trình duyệt Web (WebUI)
Thích hợp cho làm việc từ xa hoặc chia sẻ cho các máy khác trong mạng nội bộ.
- **Lệnh khởi chạy**:
  ```bash
  uv run webui.py
  ```
- **Địa chỉ truy cập**: Mở trình duyệt và truy cập `http://127.0.0.1:7860`

### 2.3. Giao diện Dòng lệnh (CLI)
Dành cho việc chạy ngầm trên server, xử lý hàng loạt hoặc tự động hóa bằng script.
- **Lệnh khởi chạy**:
  ```bash
  uv run cli.py [các_tham_số...]
  ```

---

## 🖥️ 3. HƯỚNG DẪN CHI TIẾT TRÊN GIAO DIỆN GUI (`sp.py`)

Khi khởi chạy `uv run sp.py`, bạn thực hiện quy trình dịch theo 6 bước thiết lập:

### Bước 1: Chọn Video / Audio nguồn
- Nhấn nút **Select Video/Audio** (hoặc kéo thả tập tin video như `.mp4`, `.mkv`, `.avi`, `.mov`...) vào vùng ứng dụng.

### Bước 2: Cấu hình Nhận dạng Giọng nói (ASR / STT)
- **Kênh nhận dạng (Recogn Type)**:
  - `Faster-Whisper` *(Khuyên dùng)*: Chạy cục bộ offline, tốc độ cực nhanh, độ chính xác cao.
  - `OpenAI Whisper`: Mô hình nhận dạng gốc từ OpenAI.
  - Kênh Online API: Alibaba Qwen ASR, ByteDance Volcano, Google Speech, Azure Speech...
- **Mô hình (Model Name)**: Chọn kích thước mô hình Whisper: `tiny`, `base`, `small`, `medium`, `large-v3` *(Mô hình càng lớn nhận dạng càng chính xác nhưng yêu cầu tài nguyên GPU/RAM cao hơn)*.
- **Tăng tốc GPU (CUDA)**: Tích chọn nút CUDA nếu máy bạn có card đồ họa NVIDIA để tăng tốc độ gấp 5-10 lần.
- **Phân biệt người nói (Speaker Diarization)**: Tích chọn nếu video có nhiều người thoại để phần mềm tự đánh dấu (Speaker 0, Speaker 1...).

### Bước 3: Cấu hình Dịch thuật Phụ đề (Subtitle Translation)
- **Kênh dịch (Translate Type)**:
  - `DeepSeek` / `ChatGPT` / `Claude` / `Gemini`: Dịch bằng trí tuệ nhân tạo LLM, hiểu ngữ cảnh và văn phong tự nhiên.
  - `Ollama`: Dịch offline bằng mô hình LLM cài sẵn trên máy bạn.
  - `Google Translate` / `Microsoft Translator`: Dịch máy truyền thống, miễn phí, tốc độ nhanh.
- **Ngôn ngữ nguồn & Đích**: Chọn ngôn ngữ gốc của video (ví dụ: *English*) và ngôn ngữ muốn dịch ra (ví dụ: *Vietnamese*).

### Bước 4: Cấu hình Lồng tiếng / Tổng hợp Giọng nói (TTS)
- **Kênh Lồng tiếng (TTS Type)**:
  - `Edge-TTS`: Miễn phí của Microsoft, giọng đọc tự nhiên, hỗ trợ tiếng Việt (`vi-VN-HoaiMyNeural`, `vi-VN-NamMinhNeural`) và hàng trăm giọng đọc quốc tế.
  - `F5-TTS` / `CosyVoice` / `GPT-SoVITS`: Hỗ trợ **Voice Cloning** (Tạo giọng AI nhái từ audio 5-10 giây mẫu).
  - `OpenAI TTS` / `Azure TTS` / `Minimax`: Giọng AI thương mại chất lượng studio.
- **Giọng đọc (Voice Role)**: Chọn giọng nam/nữ hoặc gán từng giọng đọc cho từng nhân vật.
- **Tốc độ đọc (Voice Rate)** & **Cao độ (Pitch)**: Tùy chỉnh tốc độ nói (+10%, -10%...) và độ trầm bổng.

### Bước 5: Cấu hình Đồng bộ Âm thanh - Video
- **Tự động chỉnh tốc độ âm thanh (Voice Autorate)**: Nén hoặc kéo dài lời thoại lồng tiếng để trùng khớp chính xác với khoảng thời gian của câu gốc.
- **Tự động chỉnh tốc độ video (Video Autorate)**: Tự động làm chậm hình ảnh video ở những đoạn thoại dịch dài hơn thoại gốc để không bị lệch hình.
- **Tách Vocal & Nhạc nền (Vocal Separation)**: Giữ lại toàn bộ tiếng động và nhạc nền gốc của video, chỉ đè giọng lồng tiếng mới vào.
- **Kiểu phụ đề (Subtitle Type)**:
  - *Phụ đề cứng (Hard Subtitle)*: Ghi trực tiếp chữ lên hình ảnh video.
  - *Phụ đề mềm (Soft Subtitle)*: Nhúng luồng phụ đề có thể bật/tắt vào file video.
  - *Phụ đề song ngữ (Dual Subtitles)*: Hiển thị song song cả tiếng gốc và tiếng dịch.

### Bước 6: Tiến hành Dịch & Hiệu chỉnh thủ công
- Nhấn nút **Start**. Phần mềm sẽ chạy qua các bước.
- **Mẹo hay**: Bạn có thể tích chọn **Manual Pause** để ứng dụng tạm dừng sau khi nhận dạng xong (cho phép bạn sửa lỗi chính tả phụ đề gốc) hoặc sau khi dịch xong (cho phép bạn trau chuốt lại câu từ dịch) trước khi tạo file video cuối cùng.

---

## 🌐 4. HƯỚNG DẪN SỬ DỤNG GIAO DIỆN WEBUI (`webui.py`)

Khi chạy `uv run webui.py`, giao diện web Gradio xuất hiện gồm các Tab:

1. **Tab Video Translation**: Dịch video trọn gói bằng giao diện đơn giản trên trình duyệt.
2. **Tab Speech to Text**: Tải lên video/audio để lấy file phụ đề `.srt`.
3. **Tab Text to Speech**: Tải lên file phụ đề `.srt` để xuất file âm thanh lồng tiếng `.mp3`/`.wav`.
4. **Tab Subtitle Translation**: Dịch file phụ đề `.srt` sang ngôn ngữ khác.
5. **Tab Tools**: Bộ công cụ tách vocal, tách nhạc nền, ghép nối audio.

---

## 💻 5. HƯỚNG DẪN SỬ DỤNG GIAO DIỆN DÒNG LỆNH (CLI)

Cú pháp lệnh tổng quát:
```bash
uv run cli.py --task <loại_nhiệm_vụ> --name "<đường_dẫn_tập_tin>" [các_options...]
```

### Các nhiệm vụ chính (`--task`):
- `vtv`: Video Translation (Dịch video全流程).
- `stt`: Speech to Text (Nhận dạng giọng nói ra phụ đề).
- `sts`: Subtitle Translation (Dịch phụ đề SRT).
- `tts`: Text to Speech (Tạo lồng tiếng từ phụ đề SRT).

### Các câu lệnh thực tế thông dụng:

#### 1. Dịch Video hoàn chỉnh (VTV):
Dịch video tiếng Anh sang tiếng Việt, lồng tiếng Edge-TTS giọng Hoài Mỹ (`vi-VN-HoaiMyNeural`) dùng GPU CUDA:
```bash
uv run cli.py --task vtv --name "D:/videos/lesson.mp4" --source_language_code en --target_language_code vi --voice_role "vi-VN-HoaiMyNeural" --cuda
```

#### 2. Nhận dạng giọng nói tạo phụ đề SRT (STT):
Sử dụng mô hình Faster-Whisper `large-v3` trên GPU CUDA:
```bash
uv run cli.py --task stt --name "D:/videos/interview.mp4" --recogn_type 0 --model_name large-v3 --cuda
```

#### 3. Dịch file phụ đề SRT (STS):
Dịch phụ đề từ tiếng Trung sang tiếng Việt:
```bash
uv run cli.py --task sts --name "D:/subs/movie.srt" --source_language_code zh-cn --target_language_code vi --translate_type 0
```

#### 4. Tạo file âm thanh lồng tiếng từ phụ đề SRT (TTS):
```bash
uv run cli.py --task tts --name "D:/subs/movie_vi.srt" --tts_type 0 --voice_role "vi-VN-NamMinhNeural"
```

#### 5. Tra cứu thông tin danh sách nhà cung cấp & ngôn ngữ:
```bash
# Liệt kê các nhà cung cấp dịch thuật / ASR / TTS
uv run cli.py --list providers

# Liệt kê danh sách các mã ngôn ngữ hỗ trợ
uv run cli.py --list languages
```

---

## ⚙️ 6. CẤU HÌNH TĂNG TỐC GPU (NVIDIA CUDA)

Dự án pyVideoTrans đã được cài đặt gói **PyTorch CUDA 12.8** đi kèm. Để tận dụng tối đa sức mạnh GPU:
1. Đảm bảo máy tính đã cài Driver NVIDIA tương thích.
2. Kiểm tra trạng thái nhận diện GPU:
   ```bash
   uv run python -c "import torch; print('CUDA Available:', torch.cuda.is_available()); print('GPU Name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"
   ```
3. Luôn bật cờ `--cuda` khi dùng CLI hoặc tích ô **CUDA** trên GUI.

---

## 🛠️ 7. XỬ LÝ LỖI THƯỜNG GẶP (TROUBLESHOOTING)

| Bệnh / Lỗi | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| **Lỗi `FFmpeg not found`** | Chưa nhận diện bộ công cụ FFmpeg trong hệ thống | Kiểm tra xem đã có `ffmpeg` trong PATH chưa hoặc chép `ffmpeg.exe` & `ffprobe.exe` vào thư mục `d:\pyvideotrans\ffmpeg\` |
| **Lỗi `CUDA out of memory`** | Bộ nhớ VRAM của card màn hình bị tràn khi nạp Whisper lớn | Đổi kích thước mô hình từ `large-v3` xuống `medium`, `small` hoặc `base` |
| **Lỗi kết nối Edge-TTS / OpenAI API** | Mạng bị ngắt kết nối hoặc nhà mạng chặn server API | Kiểm tra lại kết nối Internet hoặc bật phần mềm VPN / Proxy |
| **Giọng lồng tiếng bị lệch so với video gốc** | Lời dịch dài hơn hoặc ngắn hơn đáng kể so với tiếng gốc | Tích chọn tính năng **Voice Autorate** (Tự chỉnh tốc độ nói) và **Video Autorate** (Tự chỉnh tốc độ video) |

---

## 📖 8. TÀI NGUYÊN VÀ THAM KHẢO
- **Trang chủ & Tài liệu chính thức**: [https://pyvideotrans.com](https://pyvideotrans.com)
- **Cộng đồng Q&A và hỗ trợ sự cố AI**: [https://bbs.pyvideotrans.com](https://bbs.pyvideotrans.com)
- **Tài liệu CLI gốc**: [docs/cli.md](file:///d:/pyvideotrans/docs/cli.md)
- **Tài liệu WebUI gốc**: [docs/webui.md](file:///d:/pyvideotrans/docs/webui.md)

---
*Tài liệu được soạn thảo chi tiết tiếng Việt cho phần mềm pyVideoTrans.*
