# -*- coding: utf-8 -*-
"""
Trang cài đặt (CAI_DAT.bat): mở trang web trên máy này (chỉ 127.0.0.1) để đổi kênh dịch, chuỗi model,
API key, giọng đọc, Telegram, cấu hình lồng tiếng — thay cho DOI_MODEL / DOI_TTS / CAI_TELEGRAM (vẫn dùng được).

Đọc / ghi qua cau_hinh.py. Máy quản trị (bản clone git) có thêm tab "Cấu hình chung" để đặt giá trị cho mọi máy
rồi đẩy lên GitHub; máy nhân viên thấy các mục đó ở dạng khoá.
Thay đổi áp dụng từ lần chạy LONG_TIENG.bat tiếp theo.
"""
import contextlib
import html
import io
import os
import socket
from pathlib import Path

os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')

import cau_hinh as ch  # noqa: E402  (cau_hinh -> doi_model đã chỉnh console sang UTF-8)
import gradio as gr  # noqa: E402

ADMIN = ch.is_admin()
TABS = {
    'dich': ['dub.translate_type', 'params.ninerouter_api', 'params.ninerouter_model', 'dub.translate_parallel',
             'settings.llm_timeout', 'dub.translate_stall_minutes', 'dub.translate_qa', 'dub.translate_glossary',
             'dub.merge_fragments', 'dub.tts_speak_text'],
    'model_khac': ['params.openrouter_model', 'params.gemini_model', 'params.deepseek_model'],
    'giong': ['dub.tts_type', 'params.omnivoice_modal_url', 'params.omnivoice_modal_key',
              'params.runpod_endpoint_id', 'params.runpod_api_key', 'params.fleet_url', 'params.fleet_api_key'],
    'telegram': ['params.telegram_bot_token', 'params.telegram_chat_id', 'dub.telegram_notify'],
    'render': ['dub.is_separate', 'dub.backaudio_volume', 'dub.dub_parallel', 'dub.dub_prep_ahead',
               'dub.tts_prefetch_parallel', 'dub.tts_fit_ratio', 'dub.tts_shorten_ratio', 'dub.dub_stall_minutes',
               'dub.retries', 'dub.video_preset', 'dub.video_crf', 'dub.normalize_audio', 'dub.loudnorm_i',
               'dub.cleanup_out'],
}
NOTICE = ('Thay đổi áp dụng từ **lần chạy LONG_TIENG tiếp theo**. Đang mở MO_PHAN_MEM (giao diện pyvideotrans) '
          'thì đóng nó trước khi lưu, kẻo nó ghi đè.')


# ---------------------------------------------------------------------------
# Ô nhập theo cau_hinh.FIELDS
# ---------------------------------------------------------------------------
def _label(field, src: str) -> str:
    if src != 'chung':
        return field.label
    return field.label + (' — 🌐 cấu hình chung (sửa ở đây = sửa cho mọi máy)' if ADMIN
                          else ' — 🔒 do quản trị đặt cho mọi máy')


def _props(field, snap) -> dict:
    value, src = snap[field.id]
    props = {'label': _label(field, src), 'interactive': ADMIN or src != 'chung'}
    if field.kind == 'secret':
        props.update(value='', placeholder=f'Đang có: {ch.mask(value)} — để trống = giữ nguyên')
    elif field.kind == 'bool':
        props['value'] = bool(value)
    elif field.kind == 'auto_int':
        props['value'] = str(value)
    else:
        props['value'] = ch.to_display(field, value)
    return props


def make(fid: str, snap):
    field = ch.BY_ID[fid]
    props = _props(field, snap)
    # Ghi chú có "<ma>" (logs/qa-<ma>.txt): trang hiểu nhầm là thẻ HTML và cắt mất phần sau
    info = html.escape(ch.note(field)) or None
    if field.kind == 'bool':
        return gr.Checkbox(info=info, **props)
    if field.kind == 'choice':
        return gr.Dropdown(choices=[(lbl, v) for v, lbl in field.choices], info=info, **props)
    if field.kind in ('int', 'float'):
        return gr.Number(minimum=field.minimum, maximum=field.maximum, info=info,
                         precision=0 if field.kind == 'int' else None, **props)
    if field.kind == 'lines':
        return gr.Textbox(lines=5, info=info, **props)
    if field.kind == 'secret':
        return gr.Textbox(type='password', info=info, **props)
    return gr.Textbox(info=info, **props)


def refreshed(ids: list) -> list:
    snap = ch.snapshot()
    return [gr.update(**_props(ch.BY_ID[fid], snap)) for fid in ids]


def form(ids: list, snap):
    """Các ô + nút Lưu / Tải lại cho 1 nhóm mục. Trả về (danh sách ô, ô thông báo)."""
    boxes = [make(fid, snap) for fid in ids]
    with gr.Row():
        save_btn = gr.Button('💾 Lưu', variant='primary')
        reload_btn = gr.Button('↻ Tải lại')
    status = gr.Markdown()

    def on_save(*values):
        msgs = ch.save(dict(zip(ids, values)))
        return ['\n'.join(f'- {m}' for m in msgs)] + refreshed(ids)

    save_btn.click(on_save, inputs=boxes, outputs=[status] + boxes)
    reload_btn.click(lambda: [''] + refreshed(ids), outputs=[status] + boxes)
    return boxes, status


# ---------------------------------------------------------------------------
# Tổng quan
# ---------------------------------------------------------------------------
def overview() -> str:
    snap = ch.snapshot()
    rows = ['| Mục | Giá trị | Nguồn |', '|---|---|---|']
    for f in ch.FIELDS:
        value, src = snap[f.id]
        if f.kind == 'secret':
            shown = ch.mask(value)
        elif f.kind == 'choice':
            shown = dict(f.choices).get(value, value)
        elif f.kind == 'lines':
            shown = ' → '.join(m for m in str(value or '').split(',') if m) or '(trống)'
        else:
            shown = value
        rows.append(f'| {f.label} | {str(shown).replace("|", "/")} | '
                    f'{"🌐 chung" if src == "chung" else "máy này"} |')
    keys = [f'{info["name"]}: {len(ch.get_keys(c))} key' for c, info in ch.KEY_CHANNELS.items()]
    return (f'**Máy:** {socket.gethostname()} — '
            f'{"máy quản trị (sửa được cấu hình chung)" if ADMIN else "máy nhân viên"}  \n'
            f'**API key:** {" · ".join(keys)}\n\n' + '\n'.join(rows))


# ---------------------------------------------------------------------------
# Dịch: danh sách model 9Router + thử model
# ---------------------------------------------------------------------------
def fetch_models():
    try:
        models = ch.ninerouter_models()
    except Exception as e:  # noqa: BLE001
        return gr.update(), f'Không lấy được danh sách model: {e}'
    return gr.update(choices=models, value=None), f'9Router có {len(models)} model. Chọn rồi bấm "Thêm vào cuối chuỗi".'


def add_model(chain: str, picked):
    picked = [picked] if isinstance(picked, str) else list(picked or [])
    models = [m.strip() for m in (chain or '').splitlines() if m.strip()]
    return '\n'.join(dict.fromkeys(models + picked))


def test_chain(chain: str):
    models = [m.strip() for m in (chain or '').splitlines() if m.strip()]
    if not models:
        return [], 'Chuỗi model đang trống.'
    rows = ch.test_ninerouter(models)
    ok = sum(r[1] == 'OK' for r in rows)
    return rows, (f'{ok}/{len(rows)} model dịch được (thử cùng lúc, model treo tối đa 90 giây). '
                  f'Thử theo chuỗi đang gõ, chưa cần Lưu.')


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------
CHANNEL_NAMES = [(info['name'], c) for c, info in ch.KEY_CHANNELS.items()]


def list_keys(channel) -> str:
    keys = ch.get_keys(int(channel))
    if not keys:
        return 'Chưa có key.'
    return '\n'.join(f'{i}. `{ch.mask(k)}`' for i, k in enumerate(keys, 1))


def add_keys(channel, text: str):
    channel = int(channel)
    new = [k.strip().strip('"') for k in (text or '').replace(',', '\n').splitlines() if k.strip()]
    if not new:
        return list_keys(channel), '', 'Chưa dán key nào.'
    prefix = ch.KEY_CHANNELS[channel]['prefix']
    odd = [ch.mask(k) for k in new if prefix and not k.startswith(prefix)]
    ch.set_keys(channel, ch.get_keys(channel) + new)
    warn = f' Lưu ý: {", ".join(odd)} không bắt đầu bằng {" / ".join(prefix)}, kiểm tra lại.' if odd else ''
    return list_keys(channel), '', f'Đã thêm {len(new)} key.{warn}'


def remove_key(channel, number):
    channel = int(channel)
    keys = ch.get_keys(channel)
    try:
        n = int(number)
        removed = keys.pop(n - 1)
    except (TypeError, ValueError, IndexError):
        return list_keys(channel), f'Không có key số {number}.'
    ch.set_keys(channel, keys)
    return list_keys(channel), f'Đã xoá key {ch.mask(removed)}.'


def test_keys(channel, progress=gr.Progress()):
    channel = int(channel)
    keys = ch.get_keys(channel)
    model = (ch.channel_model(channel).split(',') or [''])[0]
    if not keys:
        return [], 'Chưa có key.'
    if not model:
        return [], 'Kênh này chưa chọn model.'
    rows = []
    for k in progress.tqdm(keys, desc='Đang thử'):
        if channel == 25:
            # 9Router: model đầu chuỗi có thể đang chết, thử key bằng cách lấy danh sách model (cần key đúng)
            rows.append((ch.mask(k), '(danh sách model)', *ch.check_ninerouter_key(k)))
            continue
        m, state, secs, text = ch.test_models(channel, [model], key=k)[0]
        rows.append((ch.mask(k), m, state, secs, text))
    return rows, f'Thử với model {model}.' if channel != 25 else 'Key 9Router đúng thì lấy được danh sách model.'


# ---------------------------------------------------------------------------
# Giọng đọc
# ---------------------------------------------------------------------------
def _quiet(fn, *args):
    """Gọi hàm in ra màn hình của doi_tts, lấy chữ in ra làm kết quả"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = fn(*args)
    return ok, buf.getvalue().strip()


def check_modal(url: str, key: str):
    import doi_tts
    saved_url, saved_key = doi_tts.remote()
    url, key = (url or saved_url).strip().rstrip('/'), (key or saved_key).strip()
    if not url or not key:
        return 'Thiếu URL hoặc key.'
    ok, out = _quiet(doi_tts.check_server, url, key)
    return ('✅ ' if ok else '❌ ') + out


def check_runpod(endpoint: str, key: str):
    import doi_tts
    saved_ep, saved_key = doi_tts.runpod()
    endpoint, key = (endpoint or saved_ep).strip().rstrip('/').split('/')[-1], (key or saved_key).strip()
    if not endpoint or not key:
        return 'Thiếu endpoint ID hoặc API key.'
    ok, out = _quiet(doi_tts.check_runpod, endpoint, key)
    return ('✅ ' if ok else '❌ ') + out


def ref_status():
    p = ch.read_json(ch.PARAMS_JSON)
    ref = str(p.get('omnivoice_ref_wav', '') or '').strip()
    path = (Path(ref) if Path(ref).is_absolute() else ch.ROOT_DIR / ref) if ref else None
    if not ref:
        return 'Đang dùng: **nhái từng câu từ video gốc**.', None
    if not path.is_file():
        return f'⚠️ Đang chọn file giọng mẫu `{ref}` nhưng không thấy file.', None
    text = p.get('omnivoice_ref_text') or '(để trống, server tự nghe)'
    return f'Đang dùng: **1 file giọng mẫu cố định** `{ref}` — lời: {text}', str(path)


def save_ref(mode: str, upload, text: str):
    if mode.startswith('Nhái'):
        ch.set_params(omnivoice_ref_wav='', omnivoice_ref_text='')
        return ref_status()
    if not upload:
        md, audio = ref_status()
        return '⚠️ Chưa chọn file giọng mẫu.\n\n' + md, audio
    import doi_tts
    try:
        length = doi_tts.cut_ref(Path(upload))
    except ValueError as e:
        md, audio = ref_status()
        return f'❌ {e}\n\n' + md, audio
    ch.set_params(omnivoice_ref_wav=f'f5-tts/{doi_tts.REF_FILE}', omnivoice_ref_text=(text or '').strip())
    md, audio = ref_status()
    return f'✅ Đã lấy {length:.1f} giây đầu làm giọng mẫu.\n\n' + md, audio


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def find_groups(token: str):
    import bao_cao_telegram as tg
    token = (token or '').strip() or tg._settings()[0]
    if not token:
        return gr.update(), 'Nhập token bot trước.'
    try:
        groups = tg._find_groups(token)
    except Exception as e:  # noqa: BLE001
        return gr.update(), f'Không đọc được tin của bot: {e}'
    if not groups:
        return gr.update(), ('Chưa thấy nhóm nào. Thêm bot vào nhóm, gõ /start@<tên bot> trong nhóm rồi bấm lại.')
    return (gr.update(choices=[(f'{t} ({cid})', cid) for cid, t in groups.items()], value=None),
            f'Thấy {len(groups)} nhóm. Chọn nhóm rồi bấm Lưu ở trên.')


def send_test():
    import bao_cao_telegram as tg
    if not tg.configured():
        return 'Chưa có token + ID nhóm đã lưu.'
    try:
        tg.send(f'✅ Máy {tg.machine()}: thử gửi từ trang cài đặt (CAI_DAT.bat).')
    except Exception as e:  # noqa: BLE001
        return f'❌ Gửi lỗi: {e}'
    return '✅ Đã gửi, xem trong nhóm Telegram.'


# ---------------------------------------------------------------------------
# Cấu hình chung
# ---------------------------------------------------------------------------
def shared_md() -> str:
    shared = ch.shared_values()
    rows = [f'- **{f.label}** = `{shared[f.store][f.key]}`' for f in ch.FIELDS if f.key in shared[f.store]]
    return ('\n'.join(rows) if rows else 'Chưa có mục nào: mọi máy dùng cài đặt riêng của mình.')


def shared_ids() -> list:
    return [fid for fid, (_, src) in ch.snapshot().items() if src == 'chung']


def apply_shared(ids):
    try:
        msgs = ch.choose_shared(list(ids or []))
    except ValueError as e:
        msgs = [str(e)]
    return '\n'.join(f'- {m}' for m in msgs), shared_md()


def push():
    ok, msg = ch.push_shared()
    return ('✅ ' if ok else '❌ ') + msg


# ---------------------------------------------------------------------------
def build() -> gr.Blocks:
    snap = ch.snapshot()
    with gr.Blocks(title='Cài đặt lồng tiếng', analytics_enabled=False) as demo:
        gr.Markdown(f'# ⚙️ Cài đặt lồng tiếng\n{NOTICE}')
        with gr.Tab('Tổng quan'):
            ov = gr.Markdown(overview())
            gr.Button('↻ Tải lại').click(overview, outputs=ov)

        with gr.Tab('Dịch'):
            boxes, _ = form(TABS['dich'], snap)
            chain_box = boxes[TABS['dich'].index('params.ninerouter_model')]
            with gr.Accordion('Chọn model từ 9Router / thử chuỗi model', open=True):
                with gr.Row():
                    fetch_btn = gr.Button('Lấy danh sách model từ 9Router')
                    pick = gr.Dropdown(label='Model trên 9Router', choices=[], multiselect=True, filterable=True)
                    add_btn = gr.Button('Thêm vào cuối chuỗi')
                fetch_msg = gr.Markdown()
                test_btn = gr.Button('🧪 Thử từng model trong chuỗi (dịch 1 câu)')
                test_msg = gr.Markdown()
                test_tbl = gr.Dataframe(headers=['Model', 'Kết quả', 'Giây', 'Trả lời / lỗi'], wrap=True)
            fetch_btn.click(fetch_models, outputs=[pick, fetch_msg])
            add_btn.click(add_model, inputs=[chain_box, pick], outputs=chain_box)
            test_btn.click(test_chain, inputs=chain_box, outputs=[test_tbl, test_msg])
            with gr.Accordion('Model của các kênh khác', open=False):
                form(TABS['model_khac'], snap)

        with gr.Tab('API key'):
            gr.Markdown('Mỗi kênh dán được nhiều key: key này bị giới hạn / hết tiền thì tự chuyển key sau. '
                        'Key chỉ lưu trên máy này (videotrans/params.json), không bao giờ lên GitHub.')
            chan = gr.Dropdown(label='Kênh', choices=CHANNEL_NAMES, value=CHANNEL_NAMES[-1][1])
            keys_md = gr.Markdown(list_keys(CHANNEL_NAMES[-1][1]))
            with gr.Row():
                new_keys = gr.Textbox(label='Dán key mới (nhiều key thì cách nhau dấu phẩy)', type='password', lines=1)
                add_k = gr.Button('➕ Thêm key')
            with gr.Row():
                del_no = gr.Number(label='Số thứ tự key cần xoá', precision=0)
                del_k = gr.Button('🗑️ Xoá key')
            key_msg = gr.Markdown()
            test_k = gr.Button('🧪 Thử từng key')
            key_tbl = gr.Dataframe(headers=['Key', 'Model', 'Kết quả', 'Giây', 'Trả lời / lỗi'], wrap=True)
            chan.change(list_keys, inputs=chan, outputs=keys_md)
            add_k.click(add_keys, inputs=[chan, new_keys], outputs=[keys_md, new_keys, key_msg])
            del_k.click(remove_key, inputs=[chan, del_no], outputs=[keys_md, key_msg])
            test_k.click(test_keys, inputs=chan, outputs=[key_tbl, key_msg])

        with gr.Tab('Giọng đọc'):
            boxes, _ = form(TABS['giong'], snap)
            url_box, mkey_box, ep_box, rkey_box = boxes[1:5]
            with gr.Row():
                chk_m = gr.Button('Kiểm tra server Modal')
                chk_r = gr.Button('Kiểm tra RunPod')
            chk_msg = gr.Markdown()
            chk_m.click(check_modal, inputs=[url_box, mkey_box], outputs=chk_msg)
            chk_r.click(check_runpod, inputs=[ep_box, rkey_box], outputs=chk_msg)
            with gr.Accordion('Giọng mẫu OmniVoice', open=True):
                md, audio = ref_status()
                ref_md = gr.Markdown(md)
                ref_audio = gr.Audio(value=audio, label='Giọng mẫu đang dùng', interactive=False)
                mode = gr.Radio(['Nhái từng câu từ video gốc (mặc định)',
                                 '1 file giọng mẫu cố định (5-15 giây, 1 người nói, không nhạc nền)'],
                                value='Nhái từng câu từ video gốc (mặc định)' if not audio else
                                '1 file giọng mẫu cố định (5-15 giây, 1 người nói, không nhạc nền)', label='Cách nhái giọng')
                upload = gr.File(label='File giọng mẫu (wav / mp3 / m4a)', type='filepath')
                ref_text = gr.Textbox(label='Lời nói CHÍNH XÁC trong ~15 giây đầu (để trống = server tự nghe)')
                gr.Button('💾 Lưu giọng mẫu', variant='primary').click(
                    save_ref, inputs=[mode, upload, ref_text], outputs=[ref_md, ref_audio])

        with gr.Tab('Telegram'):
            boxes, _ = form(TABS['telegram'], snap)
            token_box, chat_box = boxes[0], boxes[1]
            with gr.Row():
                find_btn = gr.Button('Tìm nhóm có bot')
                groups = gr.Dropdown(label='Nhóm tìm thấy', choices=[])
            tg_msg = gr.Markdown()
            find_btn.click(find_groups, inputs=token_box, outputs=[groups, tg_msg])
            groups.change(lambda g: g or gr.update(), inputs=groups, outputs=chat_box)
            gr.Button('📨 Gửi thử (token + nhóm đã lưu)').click(send_test, outputs=tg_msg)

        with gr.Tab('Lồng tiếng & render'):
            form(TABS['render'], snap)

        with gr.Tab('Cấu hình chung'):
            if ADMIN:
                gr.Markdown('Đánh dấu mục nào **mọi máy dùng chung**, bấm Lưu (lấy giá trị đang dùng trên máy này), '
                            'rồi **Đẩy lên GitHub**: máy nhân viên chạy CAP_NHAT.bat là áp dụng, không sửa được nữa. '
                            'Key, token, URL máy chủ riêng không có trong danh sách (repo GitHub công khai).')
                pick_shared = gr.CheckboxGroup(label='Mục dùng chung',
                                               choices=[(f.label, f.id) for f in ch.FIELDS if f.shareable],
                                               value=shared_ids())
                with gr.Row():
                    save_sh = gr.Button('💾 Lưu danh sách mục dùng chung', variant='primary')
                    push_btn = gr.Button('⬆️ Đẩy lên GitHub')
                sh_msg = gr.Markdown()
                sh_md = gr.Markdown(shared_md())
                save_sh.click(apply_shared, inputs=pick_shared, outputs=[sh_msg, sh_md])
                push_btn.click(push, outputs=sh_msg)
            else:
                gr.Markdown('Các mục dưới đây do quản trị đặt cho mọi máy (cập nhật bằng CAP_NHAT.bat), '
                            'máy này không sửa được:')
                gr.Markdown(shared_md())
    return demo


def main() -> None:
    print('\n   Đang mở trang cài đặt trong trình duyệt...')
    print('   Đóng cửa sổ này khi cài xong.\n')
    build().launch(server_name='127.0.0.1', inbrowser=True, quiet=True, theme=gr.themes.Soft())


if __name__ == '__main__':
    main()
