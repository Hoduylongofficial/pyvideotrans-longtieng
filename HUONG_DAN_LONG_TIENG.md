# Lồng tiếng hàng loạt 25 ngôn ngữ

Đưa vào **1 video tiếng Anh + 1 file phụ đề .srt tiếng Anh**, nhận về **25 video đã lồng
tiếng, nhúng phụ đề cứng**, mỗi ngôn ngữ một file, tên tiếng Việt — kèm thêm **1 bản
video gốc tiếng Anh chỉ nhúng phụ đề tiếng Anh** (giữ nguyên hình và tiếng gốc).

---

## PHẦN 1 — Cài đặt (chỉ làm 1 lần)

### 1.1 Cài `uv`

Mở **PowerShell** rồi dán lệnh sau:

```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Đóng PowerShell, mở lại, gõ `uv --version` để kiểm tra.

### 1.2 Cài ffmpeg

```bash
winget install Gyan.FFmpeg
```

Đóng cửa sổ, mở lại, gõ `ffmpeg -version` để kiểm tra. Bản build phải có
`--enable-libass --enable-libfribidi --enable-libharfbuzz` thì phụ đề Ả Rập và Ấn Độ
mới hiển thị đúng — bản `Gyan.FFmpeg` ở trên đã có sẵn.

### 1.3 Rubberband — đã có sẵn, không cần làm gì

`rubberband.exe` và `sndfile.dll` đã nằm sẵn trong thư mục `ffmpeg` của gói này. Nhờ nó
mà giọng đọc khi bị co giãn cho khớp hình vẫn giữ đúng cao độ, không bị méo.

*(Nếu thư mục `ffmpeg` thiếu 2 file trên, tải lại tại
https://breakfastquay.com/files/releases/rubberband-4.0.0-gpl-executable-windows.zip
rồi giải nén vào đó.)*

### 1.4 Cài thư viện Python

Mở PowerShell **ngay trong thư mục dự án** rồi chạy:

```bash
uv sync
```

Lần đầu mất khoảng 10–20 phút và tải vài GB. Những lần sau không cần chạy lại.

> Nếu vừa cài uv hoặc ffmpeg ở các bước trên thì **phải đóng cửa sổ dòng lệnh và
> mở lại** trước khi chạy, không thì Windows vẫn dùng PATH cũ và báo không tìm thấy
> lệnh dù đã cài xong.

### 1.5 Nhập API key để dịch phụ đề

1. Chạy `uv run sp.py` để mở giao diện.
2. Vào menu kênh dịch → **OpenRouter**.
3. Dán API key vào, phần model điền `deepseek/deepseek-v4.1-flash`, Max tokens `16384`.
4. Mục **Reasoning Effort** chọn `low` (để `No` thì model hay tiêu hết token vào phần
   suy luận và trả về rỗng).
5. Bấm lưu rồi đóng giao diện.

> Key lấy ở https://openrouter.ai — **xin key từ quản lý**, không dùng key cá nhân.

**Về chi phí:** khâu dịch tốn khoảng **0,6 USD/tháng** (≈15.000đ) với mức dùng hiện
tại, tính ra chỉ vài cent cho một video 25 ngôn ngữ. Đã thử thay bằng các model
miễn phí của OpenRouter (`:free`) nhưng không nên dùng cho chạy hàng loạt: phần lớn
bị chặn lỗi 429 liên tục, chậm hơn 3–7 lần, và dịch tiếng Nhật sai thể văn (dùng
văn nói thay vì văn lịch sự) lẫn sai thuật ngữ miễn trừ trách nhiệm. Xem mục
"Ghi chú kỹ thuật" nếu vẫn muốn thử.

### 1.5b Đổi model / thêm nhiều API key: `DOI_MODEL.bat`

Bấm đúp `DOI_MODEL.bat` → chọn số trong menu (đóng `MO_PHAN_MEM` và `LONG_TIENG` trước):

| Số | Việc |
|---|---|
| 1 | Về lại OpenRouter trả phí `deepseek/deepseek-v4.1-flash` (mặc định) |
| 2 | OpenRouter model miễn phí — tự lấy danh sách model `:free` mới nhất để chọn |
| 3 | Gemini (Google AI Studio) |
| 4 / 5 | DeepSeek chính hãng / Google Dịch miễn phí |
| 6 | Thêm / xoá API key — dán được nhiều key một lần |
| 7 | Kiểm tra từng key với model đang chọn (OK / lỗi + lý do) |
| 8 | Dịch thử 1 file `.srt` sang 1 ngôn ngữ, ra thư mục `_dich_thu` cạnh file srt (tên file có tên model để so sánh) |
| 9 | Đổi số ngôn ngữ dịch song song |

- Có nhiều key thì phần mềm dùng xoay vòng; key nào bị giới hạn (429), hết tiền hoặc
  sai thì tự chuyển sang key tiếp theo.
- Hạn mức free tính theo **tài khoản** (OpenRouter) / **project** (Gemini). Nhiều key
  tạo trong cùng 1 tài khoản/project **không** tăng thêm lượt — phải là key của các
  tài khoản/project khác nhau.
- Chọn model free thì tool hỏi đặt dịch song song = 1; quay về trả phí thì hỏi đặt lại 4.
- `LONG_TIENG.bat` bỏ qua ngôn ngữ đã dịch trong `subs/`. Muốn dịch lại bằng model mới
  thì dùng mục 8, hoặc xoá file `subs/<mã>.srt` tương ứng.

### 1.5c Cập nhật bản mới: `CAP_NHAT.bat`

Đóng `MO_PHAN_MEM` / `LONG_TIENG`, bấm đúp `CAP_NHAT.bat`. Nó tải bản mới nhất từ repo
GitHub private `Hoduylongofficial/pyvideotrans-longtieng`, chỉ ghi đè code, **giữ
nguyên** API key (`videotrans/params.json`), `videotrans/cfg.json`, kênh dịch + số dịch
song song đã chọn trong `dub_all.config.json`. Thư viện thay đổi thì tự chạy `uv sync`.

- Lần đầu nó hỏi **token GitHub** (lưu vào `update_token.txt`). Token do quản lý tạo:
  github.com → Settings → Developer settings → Fine-grained tokens → Generate new
  token → *Only select repositories*: `pyvideotrans-longtieng` → *Permissions*:
  **Contents: Read-only**. Token hết hạn thì xoá `update_token.txt` rồi dán token mới.
- Quản lý sửa code xong chỉ cần commit + `git push origin main`; nhân viên bấm
  `CAP_NHAT.bat` là có. Dòng đầu của commit message hiện ra cho nhân viên đọc.

### 1.6 Dự phòng: DeepSeek chính chủ (khi hết tiền OpenRouter)

Key DeepSeek đã nhập sẵn và **đã test chạy được**. Khi OpenRouter hết tiền, chỉ cần
đổi **1 dòng** trong `dub_all.config.json`:

```
"translate_type": 5
```

Trong `sp.py` → menu kênh dịch → **DeepSeek**: model để `deepseek-v4-flash`, Max
tokens `65536`, **ô "Thinking" phải bỏ trống**. Bỏ trống thì app gửi
`thinking: disabled` và model trả lời thẳng; tick vào thì nó đốt token vào phần suy
luận (đã đo: 141 token reasoning cho 1 câu dịch) và dễ trả về rỗng.

`deepseek-v4-flash` là alias của `deepseek-flash` = **DeepSeek-V4.1-Flash**, đúng
model đang dùng qua OpenRouter, nên chất lượng dịch như nhau (đã so 40 block:
khác biệt chỉ là cách diễn đạt, không có lỗi nghĩa).

> **Lưu ý giá:** đi thẳng DeepSeek **không rẻ hơn** OpenRouter.
> Output: OpenRouter 0,60 USD/1M cố định — DeepSeek 0,60 giờ thấp điểm nhưng
> **1,20 giờ cao điểm**. Input: OpenRouter 0,059 — DeepSeek 0,15–0,30.
> Giờ cao điểm của DeepSeek theo giờ VN là **08:00–11:00 và 13:00–17:00 (T2–T6)**,
> tức đúng giờ hành chính. Nếu chuyển sang DeepSeek thì nên **chạy loạt dịch vào
> buổi tối hoặc ban đêm** để ăn giá thấp điểm.

---

## PHẦN 2 — Cách dùng hằng ngày

### Bước 1 — Chuẩn bị 2 file

| File | Yêu cầu |
|---|---|
| Video | Định dạng mp4. **Không được có phụ đề cháy sẵn vào hình** — nếu video đã burn caption tiếng Anh, phụ đề dịch sẽ đè chồng lên. Xuất lại từ trình dựng với lớp caption đã tắt. |
| Phụ đề | File `.srt` tiếng Anh, thời gian khớp với video |

Để hai file cùng một thư mục, đặt tên gì cũng được.

### Bước 2 — Bấm đúp `LONG_TIENG.bat`

Kéo video từ Windows Explorer thả vào cửa sổ đen rồi Enter, sau đó kéo file `.srt` thả
vào rồi Enter. (Hoặc chọn cả 2 file kéo thẳng lên `LONG_TIENG.bat`.)

### Bước 3 — Chọn việc trong menu

```
1) Xem trước kiểu chữ phụ đề    <- LÀM CÁI NÀY TRƯỚC với video đầu tiên
2) Chạy tất cả                  <- việc chính
3) Chỉ dịch phụ đề
4) Chỉ làm vài ngôn ngữ
```

**Lần đầu với một kiểu video mới, chạy số 1 trước.** Nó dựng 25 ảnh mẫu trong thư mục
`preview/` để xem chữ có bị lỗi ô vuông ▯, có che mất nội dung quan trọng trong hình
không. Ưng rồi mới chạy số 2.

### Bước 4 — Đợi

Cứ để cửa sổ đó chạy. Máy vẫn dùng việc khác được nhưng sẽ chậm.

- Ngôn ngữ **đầu tiên lâu hơn hẳn** vì phải tách nhạc nền ra khỏi giọng nói — bình
  thường, không phải treo máy. 24 ngôn ngữ sau chạy nhanh hơn nhiều.
- Video 20 phút, 25 ngôn ngữ: dự trù vài tiếng.

**Lỡ tắt giữa chừng hoặc mất điện?** Mở lại `LONG_TIENG.bat`, làm y như cũ. Phần đã
xong sẽ được bỏ qua, chạy tiếp từ chỗ dừng.

### Bước 5 — Lấy kết quả

Cạnh video gốc sẽ có thư mục `dubbing_<tên video>`:

```
final/      <- 26 VIDEO THÀNH PHẨM (25 bản lồng tiếng + 1 bản gốc có phụ đề), lấy ở đây
subs/       <- 26 file .srt (25 ngôn ngữ + bản gốc), dùng để upload phụ đề CC lên YouTube
report.md   <- bảng tổng kết, mở bằng Notepad
logs/       <- nhật ký, chỉ cần khi có lỗi
_separate/  <- nhạc nền đã tách, xoá được khi làm xong hẳn
```

Tên file trong `final/` dạng `Tây Ban Nha (es) - tên video.mp4`. Bản gốc có tên
`Anh (gốc) (en) - tên video.mp4` (đổi tên hiển thị hoặc tắt hẳn ở mục `original_video` trong
`dub_all.config.json`). Khi chỉ làm vài ngôn ngữ bằng `--langs`, thêm `en` vào danh sách
(vd: `--langs en,ar`) nếu muốn làm cả bản gốc.

---

## PHẦN 3 — Danh sách 25 ngôn ngữ

Ả Rập · Đức · Tây Ban Nha · Pháp · Ý · Nhật · Hàn · Bồ Đào Nha · Nga · Thổ Nhĩ Kỳ ·
Ấn Độ · Trung phồn thể · Indonesia · Hà Lan · Ba Lan · Thụy Điển · Romania · Ukraine ·
Phần Lan · Đan Mạch · Philippines · Mã Lai · Hy Lạp · Séc · Thái Lan

Không có tiếng Anh vì đó là ngôn ngữ gốc.

---

## PHẦN 4 — Muốn chỉnh gì thì sửa ở đâu

Mở `dub_all.config.json` bằng Notepad. **Sửa xong nhớ lưu, giữ nguyên dấu phẩy và ngoặc.**

| Muốn gì | Sửa dòng nào |
|---|---|
| Đổi giọng đọc một ngôn ngữ | `"voice"` của ngôn ngữ đó trong mục `languages` |
| Đổi tên file xuất ra | `"name"` của ngôn ngữ đó |
| Bỏ bớt / thêm ngôn ngữ | Xoá / thêm một dòng trong `languages` |
| Chữ phụ đề to nhỏ | `subtitle_style` → `base` → `Fontsize` (17 ≈ 64px ở video 1080p) |
| Phụ đề cao thấp | `MarginV` (26 ≈ cách đáy 98px). Tăng số = đẩy lên cao |
| Chữ mỗi dòng | `maxlen` → `default` (36 cho chữ Latin), `cjk` (15 cho Trung/Nhật/Hàn) |
| Âm lượng to nhỏ | `loudnorm_i` (−14 là chuẩn YouTube; −13 to hơn, −16 nhỏ hơn) |
| Nhạc nền to nhỏ | `backaudio_volume` (0.8 mặc định; 1.4 nhạc rõ hơn, 0.5 nhạc nhẹ đi) |
| Không giữ nhạc nền nữa | `"is_separate": false` — chạy nhanh hơn nhiều |
| Không nhúng phụ đề vào hình | `"subtitle_type": 0` — nhanh hơn rất nhiều vì không phải mã hoá lại video |
| Giữ lại thư mục trung gian | `"cleanup_out": false` |

Danh sách giọng đọc đầy đủ có trong file `videotrans/voicejson/edge_tts.json`.
Tên giọng phải chép đúng y nguyên, ví dụ `de-DE-KatjaNeural`.

---

## PHẦN 5 — Gặp lỗi thì làm gì

| Hiện tượng | Cách xử lý |
|---|---|
| `Khong tim thay lenh "uv"` | Chưa cài uv, xem mục 1.1 |
| `Không tìm thấy ffmpeg trong PATH` | Chưa cài ffmpeg, xem mục 1.2 |
| `uv sync` báo lỗi mạng (`curl 56`, `Connection was reset`, `early EOF`) | Mạng rớt khi tải từ GitHub. Chạy lại `uv sync` — nó tiếp tục từ chỗ dở. Rớt nhiều lần thì đổi mạng khác hoặc bật VPN rồi chạy lại |
| `chưa có "openrouter_key"` | Chưa nhập API key, xem mục 1.5 |
| Dịch báo lỗi 429 liên tục | Đang dùng model `:free` (xem Ghi chú kỹ thuật) — đổi về `deepseek/deepseek-v4.1-flash`. Nếu đang dùng model trả phí thì hạ `"translate_parallel"` xuống 2 |
| Một vài ngôn ngữ báo LỖI | Chạy lại `LONG_TIENG.bat` — nó tự làm tiếp phần thiếu. Vẫn lỗi thì mở file trong `logs/` gửi cho quản lý |
| Phụ đề bị ô vuông ▯ | Máy thiếu font. Chạy Windows Update, hoặc cài gói ngôn ngữ tương ứng |
| Phụ đề chồng lên chữ có sẵn trong video | Video gốc đã burn caption. Phải xuất lại video không có caption |
| Giọng đọc nghe nhanh quá | `dub_all.config.json`: đổi `"voice_autorate": false` và `"video_autorate": true` |
| Muốn làm lại một ngôn ngữ | Xoá file video của ngôn ngữ đó trong `final/` rồi chạy lại |

---

## Ghi chú kỹ thuật

- Phần mềm gốc: pyvideotrans (GPL-3.0). Bộ này đã được vá thêm:
  bổ sung mã ngôn ngữ Phần Lan + Đan Mạch, thêm tham số `--source_srt`/`--target_srt`
  cho `cli.py` (nhờ đó bỏ qua hoàn toàn bước nhận dạng giọng nói), cho phép đặt kiểu
  phụ đề riêng cho từng ngôn ngữ, và sửa lỗi đọc sai tên thiết lập max token của
  OpenRouter.
- **Bỏ yêu cầu cài Git khi `uv sync`** (09/2026): `chatterbox-tts` khai báo phụ thuộc
  `resemble-perth` theo dạng `git+https://github.com/resemble-ai/Perth.git`, nên máy
  cài mới phải có Git và phải clone được từ GitHub — ở VN hay đứt giữa chừng với lỗi
  `curl 56 / early EOF`. PyPI có sẵn `resemble-perth` **đúng bản 1.0.1** dạng wheel
  thuần Python, nên `pyproject.toml` đã thêm `"resemble-perth==1.0.1"` vào
  `[tool.uv] override-dependencies` để `uv` lấy từ PyPI. Sau khi vá, `uv.lock` không
  còn nguồn git nào, cài đặt không cần Git nữa.
- Kênh lồng tiếng là Edge-TTS, miễn phí, không cần key. Chỉ khâu dịch phụ đề mới tốn
  tiền API, khoảng 0,6 USD/tháng ở mức dùng hiện tại.
- **Đã thử và loại các phương án miễn phí** (09/2026):
  - *Gemini API free tier*: từ 28/05/2026 Google chỉ cấp "auth key" (dạng `AQ....`)
    gắn với service account của một project Google Cloud, bắt buộc project phải bật
    Billing và API "Generative Language" thì key mới chạy. Chưa bật thì mọi request
    trả về lỗi 401 `ACCESS_TOKEN_TYPE_UNSUPPORTED`.
  - *Model `:free` trên OpenRouter*: `qwen3.8-27b`, `gemma-4-31b` bị chặn 429 ở cả
    6/6 lần thử; `glm-5.2` và `nemotron-3-super-120b` hỏng ở tiếng Nhật. Hai model
    chạy được (`ling-3.0-flash-vl`, `glm-5.2`) dịch tiếng Tây Ban Nha ngang ngửa
    deepseek nhưng chậm hơn 3–7 lần. Riêng `nemotron` đổi số đọc thành chữ số
    (`uno punto uno cero…` → `1.1000`) làm Edge-TTS đọc sai, và `ling` dịch tiếng
    Nhật bằng văn nói cùng sai thuật ngữ `投資助言` trong câu miễn trừ trách nhiệm.
  - Kết luận: giữ `deepseek/deepseek-v4.1-flash`; tiền tiết kiệm được không đáng so
    với rủi ro sai bản dịch và hỏng giọng đọc.
- Tách nhạc nền dùng model UVR-MDX-NET-Inst_HQ_4, tự tải về lần đầu (59 MB).
- Âm lượng đầu ra chuẩn hoá về −14 LUFS bằng loudnorm 2 lượt.
