def openwin():
    from PySide6 import QtWidgets
    from PySide6.QtCore import Qt
    from videotrans.util.help_misc import show_error
    from videotrans.configure.config import tr, params, app_cfg
    from videotrans.util.TestSrtTrans import TestSrtTrans
    from videotrans import translator
    from videotrans.translator._ninerouter import normalize_ninerouter_url
    from videotrans.winform._helpers import make_feed_translator, make_setallmodels
    from videotrans.component.set_form import NineRouterForm

    winobj = NineRouterForm()
    app_cfg.child_forms['ninerouter'] = winobj
    winobj.update_ui()

    feed = make_feed_translator(winobj, "test")

    def _collect():
        url = normalize_ninerouter_url(winobj.ninerouter_api.text())
        winobj.ninerouter_api.setText(url)
        params["ninerouter_api"] = url
        params["ninerouter_key"] = winobj.ninerouter_key.text().strip()
        params["ninerouter_model"] = winobj.ninerouter_model.currentText().strip()
        params["ninerouter_max_token"] = winobj.max_token.text().strip() or 8192
        params["ninerouter_reasoning_effort"] = winobj.reasoning_effort.currentText()

    def test():
        _collect()
        if not params["ninerouter_api"]:
            return show_error('Chưa nhập API URL của 9Router')
        if not params["ninerouter_model"]:
            return show_error('Chưa chọn model (bấm "Lấy danh sách model")')
        winobj.test.setText(tr("Testing..."))
        params.save()
        task = TestSrtTrans(parent=winobj, translator_type=translator.NINEROUTER_INDEX)
        task.uito.connect(feed)
        task.start()

    def fetch_models():
        import httpx
        _collect()
        if not params["ninerouter_api"]:
            return show_error('Chưa nhập API URL của 9Router')
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            resp = httpx.get(params["ninerouter_api"] + '/models', timeout=20,
                             headers={'Authorization': f'Bearer {params["ninerouter_key"]}'})
            resp.raise_for_status()
            ids = sorted({m['id'] for m in resp.json().get('data', []) if m.get('id')})
        except Exception as e:  # noqa: BLE001
            return show_error(f'Không lấy được danh sách model từ 9Router:\n{e}')
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if not ids:
            return show_error('9Router không trả về model nào. Kiểm tra đã kết nối nhà cung cấp trên dashboard chưa.')
        # 触发 textChanged -> make_setallmodels，同步下拉框并保存到 cfg.json
        winobj.edit_allmodels.setPlainText(','.join(ids))
        QtWidgets.QMessageBox.information(winobj, "OK", f'Đã lấy {len(ids)} model.')

    def save():
        _collect()
        params.save()
        winobj.close()

    winobj.set.clicked.connect(save)
    winobj.edit_allmodels.textChanged.connect(make_setallmodels(winobj, 'ninerouter_model', 'ninerouter_model'))
    winobj.fetch_models.clicked.connect(fetch_models)
    winobj.test.clicked.connect(test)
    winobj.show()
