from PySide6 import QtCore, QtWidgets
from videotrans.configure.config import tr, settings, params


class Ui_ninerouterform(object):
    def setupUi(self, ninerouterform):
        self.has_done = False
        ninerouterform.setObjectName("ninerouterform")
        ninerouterform.setWindowModality(QtCore.Qt.NonModal)
        ninerouterform.resize(600, 620)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(ninerouterform.sizePolicy().hasHeightForWidth())
        ninerouterform.setSizePolicy(sizePolicy)
        ninerouterform.setMaximumSize(QtCore.QSize(600, 620))

        v1 = QtWidgets.QVBoxLayout(ninerouterform)

        self.label_0 = QtWidgets.QLabel()
        self.label_0.setWordWrap(True)
        self.label_0.setText('9Router: gộp Claude / Gemini / DeepSeek / OpenRouter... thành 1 API chuẩn OpenAI. '
                             'Lấy URL và key ở mục "Endpoint & Key" trên dashboard 9Router.')
        v1.addWidget(self.label_0)

        h_api = QtWidgets.QHBoxLayout()
        self.label_api = QtWidgets.QLabel()
        self.label_api.setMinimumSize(QtCore.QSize(0, 35))
        self.ninerouter_api = QtWidgets.QLineEdit()
        self.ninerouter_api.setMinimumSize(QtCore.QSize(0, 35))
        self.ninerouter_api.setObjectName("ninerouter_api")
        self.ninerouter_api.setPlaceholderText("https://ten-mien-9router-cua-ban/v1")
        h_api.addWidget(self.label_api)
        h_api.addWidget(self.ninerouter_api)
        v1.addLayout(h_api)

        h_key = QtWidgets.QHBoxLayout()
        self.label_2 = QtWidgets.QLabel()
        self.label_2.setMinimumSize(QtCore.QSize(0, 35))
        self.ninerouter_key = QtWidgets.QLineEdit()
        self.ninerouter_key.setMinimumSize(QtCore.QSize(0, 35))
        self.ninerouter_key.setObjectName("ninerouter_key")
        self.ninerouter_key.setPlaceholderText("sk-...")
        h_key.addWidget(self.label_2)
        h_key.addWidget(self.ninerouter_key)
        v1.addLayout(h_key)

        h_token = QtWidgets.QHBoxLayout()
        label_token = QtWidgets.QLabel()
        label_token.setText(tr("Maximum output token"))
        self.max_token = QtWidgets.QLineEdit()
        self.max_token.setMinimumSize(QtCore.QSize(0, 35))
        self.max_token.setObjectName("max_token")
        h_token.addWidget(label_token)
        h_token.addWidget(self.max_token)
        v1.addLayout(h_token)

        hreason = QtWidgets.QHBoxLayout()
        hreason.addWidget(QtWidgets.QLabel(tr('Reasoning Effort')))
        self.reasoning_effort = QtWidgets.QComboBox()
        self.reasoning_effort.addItems(['No', 'low', 'medium', 'high'])
        hreason.addWidget(self.reasoning_effort)
        v1.addLayout(hreason)

        h_model = QtWidgets.QHBoxLayout()
        self.label_selectmodel = QtWidgets.QLabel()
        self.label_selectmodel.setText(tr("Select model"))
        self.ninerouter_model = QtWidgets.QComboBox()
        self.ninerouter_model.setMinimumSize(QtCore.QSize(0, 35))
        self.ninerouter_model.setObjectName("ninerouter_model")
        # 9Router 的模型名（含 combo 名）由用户在面板里自定义，允许直接输入
        self.ninerouter_model.setEditable(True)
        self.ninerouter_model.setToolTip('Nhập nhiều model cách nhau dấu phẩy để tự chuyển khi lỗi, vd:\n'
                                         'ag/claude-sonnet-4-6,gemini/gemini-3.6-flash,ds/deepseek-v4-flash\n'
                                         'Model đầu bị lỗi 404 / 429 / hết tiền thì tự dùng model tiếp theo.')
        self.fetch_models = QtWidgets.QPushButton()
        self.fetch_models.setMinimumSize(QtCore.QSize(0, 35))
        self.fetch_models.setText('Lấy danh sách model')
        self.fetch_models.setCursor(QtCore.Qt.PointingHandCursor)
        h_model.addWidget(self.label_selectmodel)
        h_model.addWidget(self.ninerouter_model, 1)
        h_model.addWidget(self.fetch_models)
        v1.addLayout(h_model)
        self.label_chain = QtWidgets.QLabel('Có thể gõ nhiều model cách nhau dấu phẩy (vd: ag/claude-sonnet-4-6,gemini/gemini-3.6-flash). '
                                            'Model đầu lỗi 404 / 429 / hết tiền thì tự chuyển sang model sau.')
        self.label_chain.setWordWrap(True)
        v1.addWidget(self.label_chain)

        self.label_allmodels = QtWidgets.QLabel()
        self.label_allmodels.setText(
            tr("Fill in all available models, separated by commas. After filling in, you can select them above"))
        v1.addWidget(self.label_allmodels)

        self.edit_allmodels = QtWidgets.QPlainTextEdit()
        self.edit_allmodels.setObjectName("edit_allmodels")
        v1.addWidget(self.edit_allmodels)

        self.label_4 = QtWidgets.QLabel()
        self.template = QtWidgets.QPlainTextEdit()
        self.template.setObjectName("template")
        self.template.setReadOnly(True)
        self.template.setMaximumHeight(60)
        v1.addWidget(self.label_4)
        v1.addWidget(self.template)

        h4 = QtWidgets.QHBoxLayout()
        self.set = QtWidgets.QPushButton()
        self.set.setMinimumSize(QtCore.QSize(0, 35))
        self.set.setObjectName("set")
        self.test = QtWidgets.QPushButton()
        self.test.setMinimumSize(QtCore.QSize(0, 30))
        self.test.setObjectName("test")
        self.test.setText(tr("Test"))
        h4.addWidget(self.set)
        h4.addWidget(self.test)
        v1.addLayout(h4)
        self.template.setPlainText(tr("Prompt: Please open the {} file directly to modify it", 'ninerouter', 'ninerouter'))

        self.retranslateUi(ninerouterform)
        QtCore.QMetaObject.connectSlotsByName(ninerouterform)

    def update_ui(self):
        allmodels_str = str(settings.get('ninerouter_model', ''))
        allmodels = [m for m in allmodels_str.split(',') if m.strip()]
        self.ninerouter_model.clear()
        self.ninerouter_model.addItems(allmodels)
        self.edit_allmodels.setPlainText(allmodels_str)

        self.ninerouter_api.setText(str(params.get("ninerouter_api", '')))
        self.ninerouter_key.setText(str(params.get("ninerouter_key", '')))
        _cur_model = str(params.get("ninerouter_model", '')).strip()
        if _cur_model and _cur_model not in allmodels:
            self.ninerouter_model.insertItem(0, _cur_model)
        self.ninerouter_model.setCurrentText(_cur_model)
        self.max_token.setText(str(params.get("ninerouter_max_token", '')))
        self.reasoning_effort.setCurrentText(params.get("ninerouter_reasoning_effort", "No"))

    def retranslateUi(self, ninerouterform):
        ninerouterform.setWindowTitle("9Router")
        self.label_api.setText(tr("API URL"))
        self.label_2.setText(tr("SK"))
        self.label_4.setText(tr("{lang} represents the target language name, do not delete it."))
        self.set.setText(tr('Save'))
