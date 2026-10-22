# -*- coding: utf-8 -*-
"""Cấu hình chung cho mọi máy: cau_hinh_chung.json ở gốc dự án, đi theo GitHub (CAP_NHAT.bat).

Máy quản trị sửa bằng CAI_DAT.bat rồi đẩy lên; máy nhân viên cập nhật là áp dụng. Mục nào có trong file
này thì thắng giá trị riêng của máy, mục nào không có thì máy tự chỉnh như cũ.

    {"params": {...videotrans/params.json}, "settings": {...videotrans/cfg.json},
     "dub_all": {...dub_all.config.json}}

Repo GitHub công khai: key / token / mật khẩu và URL máy chủ riêng (9Router, Modal, RunPod) không bao giờ
được đọc từ file này, kể cả khi lỡ ghi vào. File thiếu / hỏng thì coi như rỗng (phần mềm chạy như cũ).
Chỉ dùng thư viện chuẩn: dub_all.py nạp file này mà không kéo theo cả videotrans.
"""
import json
import re
from pathlib import Path

SHARED_NAME = 'cau_hinh_chung.json'
SECTIONS = ('params', 'settings', 'dub_all')
# Tên mục là bí mật hoặc địa chỉ máy chủ riêng -> chỉ nằm trên từng máy
_PRIVATE_RE = re.compile(r'key|token|secret|pass|miyue|access|authkey|appid|_api$|_url$|endpoint|proxy|chat_id',
                         re.I)


def is_private(name: str) -> bool:
    return bool(_PRIVATE_RE.search(str(name)))


def shared_path(root=None) -> Path:
    return Path(root or Path(__file__).resolve().parents[2]) / SHARED_NAME


def read_all(root=None) -> dict:
    """{section: {mục: giá trị}} đã bỏ mục riêng tư / ghi chú; lỗi thì {}."""
    try:
        data = json.loads(shared_path(root).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for section in SECTIONS:
        values = data.get(section)
        if isinstance(values, dict):
            out[section] = {k: v for k, v in values.items()
                            if isinstance(k, str) and not k.startswith('_') and not is_private(k)}
    return out


def section(name: str, root=None) -> dict:
    return read_all(root).get(name, {})
