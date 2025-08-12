# app/ranking.py

import os
import requests
import datetime
import json
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QFrame, QInputDialog, QListWidgetItem
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import QPixmap, QIntValidator, QCursor

from qfluentwidgets import (
    FluentIcon as FIF, InfoBar, InfoBarPosition,
    PushButton, SwitchButton, ComboBox,
    RoundMenu, Action, MenuAnimationType, ToolTipFilter, ToolTipPosition,
    ListWidget, TextEdit # <-- 导入 qfluentwidgets 提供的 ListWidget 和 TextEdit
)

from .download import download_manager, cookie_manager
from .config_manager import config_manager, get_config


class RankingFetcherThread(QThread):
    progress_signal = pyqtSignal(str, str)
    ids_fetched = pyqtSignal(list, str, str, str)
    error_signal = pyqtSignal(str)

    def __init__(self, url_template, pages_to_fetch, ranking_type_name, ranking_date_str, download_path_suffix):
        super().__init__()
        self.url_template = url_template
        self.pages_to_fetch = pages_to_fetch
        self.ranking_type_name = ranking_type_name
        self.ranking_date_str = ranking_date_str
        self.download_path_suffix = download_path_suffix
        self.illust_ids = []
        self.is_stopped = False

    def run(self):
        self.illust_ids = []
        self.progress_signal.emit(f"正在获取 {self.ranking_type_name} 作品ID...", "0 KB/s")

        config = get_config()
        cookie = cookie_manager.get_cookie()
        if not cookie:
            self.error_signal.emit("请在设置中配置有效的 Pixiv Cookie！")
            self.ids_fetched.emit([], "", "", "")
            return

        headers = {
            "cookie": f"PHPSESSID={cookie}",
            "referer": "https://www.pixiv.net",
            "Connection": "close",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        proxies = self._get_proxies()

        errors = 0
        for i in range(1, self.pages_to_fetch + 1):
            if self.is_stopped:
                self.progress_signal.emit("作品ID获取已停止。", "0 KB/s")
                self.ids_fetched.emit([], "", "", "")
                return

            current_url = f"{self.url_template}{i}&format=json"
            self.progress_signal.emit(f"正在访问第 {i}/{self.pages_to_fetch} 页...", "0 KB/s")

            try:
                response = requests.get(current_url, headers=headers, proxies=proxies, timeout=(8.5, 10))
                response.raise_for_status()

                data = response.json()
                if data.get('error'):
                    self.error_signal.emit(f"API返回错误: {data.get('message', '未知错误')}")
                    break

                for item in data.get('contents', []):
                    illust_id = str(item.get('illust_id'))
                    if illust_id and illust_id not in self.illust_ids:
                        self.illust_ids.append(illust_id)
                errors = 0

            except requests.exceptions.RequestException as e:
                errors += 1
                self.progress_signal.emit(f"访问失败【{errors}】次！错误: {e}。正在重新访问...", "0 KB/s")
                if errors >= 5:
                    self.error_signal.emit(f"访问失败超过【{errors}】次！自动结束本次任务。")
                    break
                self.sleep(2)
            except json.JSONDecodeError:
                errors += 1
                self.progress_signal.emit(f"JSON解析失败【{errors}】次！响应内容可能不是有效JSON。正在重新访问...",
                                          "0 KB/s")
                if errors >= 5:
                    self.error_signal.emit(f"JSON解析失败超过【{errors}】次！自动结束本次任务。")
                    break
                self.sleep(2)
            except Exception as e:
                self.error_signal.emit(f"发生未知错误: {e}")
                break

        if self.illust_ids:
            self.progress_signal.emit(f"已获取 {len(self.illust_ids)} 个作品ID。", "0 KB/s")
            self.ids_fetched.emit(self.illust_ids, self.download_path_suffix, self.ranking_type_name, self.ranking_date_str)
        else:
            self.progress_signal.emit("未获取到任何作品ID。", "0 KB/s")
            self.ids_fetched.emit([], "", "", "")

    def stop(self):
        self.is_stopped = True

    def _get_proxies(self):
        p = get_config().get('proxy', {});
        t, a, p_ = p.get('type', '0'), p.get('address', ''), p.get('port', '')
        if t == '0' or not a or not p_: return None
        proto = 'socks5' if t == '2' else 'http';
        return {'http': f"{proto}://{a}:{p_}", 'https': f"{proto}://{a}:{p_}"}


class Ranking(QWidget):
    LEFT_BORDER_COLOR = "#6ac0fa"
    RIGHT_BORDER_COLOR = "#bd88ff"
    BORDER_THICKNESS = 3
    COMMON_BORDER_RADIUS = 9

    GRADIENT_BACKGROUND_QSS = f"""
        qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {LEFT_BORDER_COLOR}, stop:1 {RIGHT_BORDER_COLOR})
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ranking_fetcher_thread = None
        self._download_item_map = {}

        self.current_ranking_illust_ids = set()
        self.current_ranking_downloaded_ids = set()
        self.current_ranking_metadata_path = None
        self.current_ranking_type_name = None
        self.current_ranking_date_str = None
        self.total_illusts_for_current_ranking = 0
        self.completed_illusts_for_current_ranking = 0
        self.is_ranking_download_active = False
        self.is_ranking_paused = False

        self.initUI()
        self.connect_signals()
        self.update_status_bar()
        self.append_log("排行榜界面初始化完成。")
        self.config_initial()
        # 1. 为 Ranking 窗口本身设置右键菜单策略
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        logo_label = QLabel()
        pixmap = QPixmap("images/logo.png")
        if not pixmap.isNull():
            logo_label.setPixmap(pixmap.scaledToWidth(220, Qt.SmoothTransformation))
        else:
            logo_label.setText("Pixiv排行榜下载")
            logo_label.setStyleSheet("font-size: 32px; color: #83a4d4; font-weight: bold;")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setStyleSheet("margin-bottom: 20px;")

        ranking_selection_frame = QFrame(self)
        ranking_selection_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e0eafc, stop:1 #cfdef3);
                border-radius: 9px;
                border: 1px solid #c0c0c0;
            }
        """)
        ranking_selection_layout = QHBoxLayout(ranking_selection_frame)
        ranking_selection_layout.setContentsMargins(20, 20, 20, 20)
        ranking_selection_layout.setSpacing(15)

        self.ranking_type_combo = ComboBox(self)
        self.ranking_type_combo.addItems([
            "日榜", "周榜", "月榜", "自定义日榜",
            "新人排行榜", "原创排行榜", "受男性欢迎", "受女性欢迎"
        ])
        self.ranking_type_combo.setCurrentIndex(0)
        ranking_selection_layout.addWidget(self.ranking_type_combo, 1)

        self.start_download_btn = PushButton("开始下载", self)
        self.start_download_btn.setIcon(FIF.DOWNLOAD)
        self.start_download_btn.setMinimumHeight(40)
        self.start_download_btn.clicked.connect(self.start_ranking_download)
        ranking_selection_layout.addWidget(self.start_download_btn)

        self.pause_resume_btn = PushButton("暂停下载", self)
        self.pause_resume_btn.setIcon(FIF.PAUSE)
        self.pause_resume_btn.setMinimumHeight(40)
        self.pause_resume_btn.setEnabled(False)
        self.pause_resume_btn.clicked.connect(self.toggle_pause_resume_all_ranking)
        ranking_selection_layout.addWidget(self.pause_resume_btn)

        self.stop_all_btn = PushButton("停止下载", self)
        self.stop_all_btn.setIcon(FIF.STOP_WATCH)
        self.stop_all_btn.setMinimumHeight(40)
        self.stop_all_btn.setEnabled(False)
        self.stop_all_btn.clicked.connect(self._stop_all_ranking_tasks)
        ranking_selection_layout.addWidget(self.stop_all_btn)


        self.ranking_selection_h_layout = QHBoxLayout()
        self.ranking_selection_h_layout.setContentsMargins(0, 0, 0, 0)
        self.ranking_selection_h_layout.addStretch(1)
        self.ranking_selection_h_layout.addWidget(ranking_selection_frame, 5)
        self.ranking_selection_h_layout.addStretch(1)

        # 修改这里，使用 qfluentwidgets.ListWidget 和 qfluentwidgets.TextEdit
        download_list_container, self.download_list_widget = self.create_area_widget("下载列表", ListWidget)
        log_output_container, self.log_output = self.create_area_widget("操作日志", TextEdit)
        self.log_output.setReadOnly(True)

        self.log_output.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_output.customContextMenuRequested.connect(self.show_log_context_menu)

        self.download_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.download_list_widget.customContextMenuRequested.connect(self.show_download_list_context_menu)

        inner_content_h_layout = QHBoxLayout()
        inner_content_h_layout.setContentsMargins(0, 0, 0, 0)
        inner_content_h_layout.setSpacing(10)
        inner_content_h_layout.addWidget(download_list_container, 3)
        inner_content_h_layout.addWidget(log_output_container, 17)

        self.content_wrapper_widget = QWidget(self)
        self.content_wrapper_widget.setLayout(inner_content_h_layout)

        main_content_h_layout = QHBoxLayout()
        main_content_h_layout.setContentsMargins(0, 0, 0, 0)
        main_content_h_layout.addStretch(1)
        main_content_h_layout.addWidget(self.content_wrapper_widget, 5)
        main_content_h_layout.addStretch(1)

        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(10, 0, 10, 5)
        status_layout.setSpacing(10)
        label_style = "QLabel { color: #666; font-size: 11px; background-color: rgba(240, 240, 240, 0.8); padding: 3px 8px; border-radius: 5px; }"

        self.proxy_info_label = QLabel("代理: N/A")
        self.proxy_info_label.setStyleSheet(label_style)
        self.thread_info_label = QLabel("线程: N/A")
        self.thread_info_label.setStyleSheet(label_style)
        self.speed_label = QLabel("速度: 0 KB/s")
        self.speed_label.setStyleSheet(label_style)
        self.r18_toggle = SwitchButton(self)
        self.r18_toggle.setText("包含 R18 作品")
        self.r18_toggle.setChecked(False)
        self.r18_toggle.installEventFilter(ToolTipFilter(self.r18_toggle, 0, ToolTipPosition.TOP))
        self.r18_toggle.setToolTip("开启后将下载R18作品 (仅对部分榜单有效)")
        self.cookie_info_label = QLabel("账号: N/A")
        self.cookie_info_label.setStyleSheet(label_style)

        status_layout.addWidget(self.proxy_info_label)
        status_layout.addWidget(self.thread_info_label)
        status_layout.addWidget(self.speed_label)
        status_layout.addStretch()
        status_layout.addWidget(self.r18_toggle)
        status_layout.addWidget(self.cookie_info_label)

        main_layout.addStretch(1)
        main_layout.addWidget(logo_label)
        main_layout.addLayout(self.ranking_selection_h_layout)
        main_layout.addLayout(main_content_h_layout, 9)
        main_layout.addStretch(2)
        main_layout.addLayout(status_layout)

    def create_area_widget(self, title, widget_class):
        main_container = QWidget(self)
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(title, alignment=Qt.AlignCenter,
                       styleSheet="font: 16px 'Segoe UI', 'Microsoft YaHei'; color:#666; font-weight: bold; margin-bottom: 5px;")
        main_layout.addWidget(label)

        content_widget = widget_class(main_container)
        content_widget.setObjectName(f"{title.replace(' ', '')}InnerWidget")
        content_widget.setContextMenuPolicy(Qt.CustomContextMenu)

        # Define these variables at the beginning of the function
        # so they are always available in both if and else branches.
        border_thickness = self.BORDER_THICKNESS
        common_border_radius = self.COMMON_BORDER_RADIUS

        if title == "操作日志":
            log_outer_gradient_frame = QFrame(main_container)
            log_outer_gradient_frame.setObjectName("logOuterGradientFrame")
            log_outer_gradient_frame.setStyleSheet(
                f"""
                #logOuterGradientFrame {{
                    background: {self.GRADIENT_BACKGROUND_QSS};
                    border-radius: {common_border_radius}px;
                    border: none;
                }}
                """
            )

            log_middle_solid_frame = QFrame(log_outer_gradient_frame) # Parent is log_outer_gradient_frame
            log_middle_solid_frame.setObjectName("logMiddleSolidFrame")
            log_middle_solid_frame.setStyleSheet(
                f"""
                #logMiddleSolidFrame {{
                    background-color: transparent;
                    border-radius: {common_border_radius}px;
                    border-left: {border_thickness}px solid {self.LEFT_BORDER_COLOR};
                    border-right: {border_thickness}px solid {self.RIGHT_BORDER_COLOR};
                }}
                """
            )

            log_inner_white_frame = QFrame(log_middle_solid_frame) # Parent is log_middle_solid_frame
            log_inner_white_frame.setObjectName("logInnerWhiteFrame")
            log_inner_white_frame.setStyleSheet(
                f"""
                #logInnerWhiteFrame {{
                    background-color: white;
                    border-radius: {common_border_radius - border_thickness}px;
                    border: none;
                }}
                """
            )

            content_widget.setStyleSheet(
                f"""
                #{content_widget.objectName()} {{
                    border: none;
                    border-radius: {common_border_radius - border_thickness}px;
                    background-color: transparent;
                    font: 14px 'Segoe UI', 'Microsoft YaHei';
                    padding: 5px;
                    color: {get_config().get('color', {}).get('ranking_new', '#333333')};
                }}
                /* 移除了滚动条样式，让其使用qfluentwidgets默认样式 */
                """
            )

            inner_white_frame_layout = QVBoxLayout(log_inner_white_frame)
            inner_white_frame_layout.setContentsMargins(0, 0, 0, 0)
            inner_white_frame_layout.addWidget(content_widget)
            log_inner_white_frame.setLayout(inner_white_frame_layout) # Set layout for inner_white_frame

            middle_solid_frame_layout = QVBoxLayout(log_middle_solid_frame)
            middle_solid_frame_layout.setContentsMargins(0, 0, 0, 0)
            middle_solid_frame_layout.addWidget(log_inner_white_frame)
            log_middle_solid_frame.setLayout(middle_solid_frame_layout) # Set layout for middle_solid_frame

            outer_gradient_frame_layout = QVBoxLayout(log_outer_gradient_frame)
            outer_gradient_frame_layout.setContentsMargins(0, border_thickness, 0, border_thickness)
            outer_gradient_frame_layout.addWidget(log_middle_solid_frame) # Corrected variable name
            log_outer_gradient_frame.setLayout(outer_gradient_frame_layout) # Set layout for outer_gradient_frame

            main_layout.addWidget(log_outer_gradient_frame, 1)

        else: # This is for QListWidget (e.g., "下载列表")
            # Revert to a style similar to user.py/tag.py for list widgets
            content_widget.setStyleSheet(
                f"""
                #{content_widget.objectName()} {{
                    border: {border_thickness}px solid {self.LEFT_BORDER_COLOR}; /* Use defined border thickness and color */
                    border-radius: {common_border_radius}px; /* Use defined border radius */
                    background-color: white; /* Set background to white */
                    font: 14px 'Segoe UI', 'Microsoft YaHei';
                    padding: 5px;
                    color: #333333;
                }}
                #{content_widget.objectName()}::item {{ padding: 5px; }}
                #{content_widget.objectName()}::item:alternate {{ background-color: #f0f0f0; }}
                #{content_widget.objectName()} QListWidget::item:selected {{ background-color: rgba(131, 164, 212, 0.2); color: black; }}
                /* 移除了滚动条样式，让其使用qfluentwidgets默认样式 */
                """
            )
            main_layout.addWidget(content_widget, 1)

        return main_container, content_widget

    def connect_signals(self):
        # 修改信号连接，槽函数需要接收新的 catalog 参数
        download_manager.task_progress.connect(self.on_download_progress)
        download_manager.task_finished.connect(self.on_download_finished)
        download_manager.speed_updated.connect(self.update_speed_display)
        config_manager.config_changed.connect(self.update_status_bar)
        # 2. 为 Ranking 窗口本身设置右键菜单策略
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_blank_area_context_menu)


    def start_ranking_download(self):
        if self.ranking_fetcher_thread and self.ranking_fetcher_thread.isRunning():
            self.create_info_bar("正在获取作品ID，请稍候。", is_error=True)
            return
        if self.is_ranking_download_active:
            self.create_info_bar("已有排行榜下载任务正在进行中，请等待其完成或停止。", is_error=True)
            return

        self.log_output.clear()
        self.download_list_widget.clear()
        self._download_item_map.clear()
        self.speed_label.setText("速度: 0 KB/s")
        self.enabled_false()

        self.current_ranking_illust_ids.clear()
        self.current_ranking_downloaded_ids.clear()
        self.current_ranking_metadata_path = None
        self.current_ranking_type_name = None
        self.current_ranking_date_str = None
        self.total_illusts_for_current_ranking = 0
        self.completed_illusts_for_current_ranking = 0
        self.is_ranking_download_active = True
        self.is_ranking_paused = False
        self.pause_resume_btn.setText("暂停下载")
        self.pause_resume_btn.setIcon(FIF.PAUSE)


        selected_type = self.ranking_type_combo.currentText()
        is_r18 = self.r18_toggle.isChecked()

        url_template = ""
        pages_to_fetch = 0
        ranking_type_name = ""
        ranking_date_display_str = ""
        folder_date_str = ""

        current_day_str = self.date_("day")
        current_ri_str = self.date_("ri")
        current_week_str = self.date_("week")
        current_zhou_str = self.date_("zhou")
        current_month_str = self.date_("month")
        current_yue_str = self.date_("yue")
        current_folder_date = self.date_("folder_date")

        if selected_type == "日榜":
            ranking_date_display_str = current_ri_str
            folder_date_str = current_folder_date
            download_path_suffix = f"Daily/{folder_date_str}"
            if is_r18:
                url_template = "https://www.pixiv.net/ranking.php?mode=daily_r18&p="
                pages_to_fetch = 3
                ranking_type_name = f"日榜 ({ranking_date_display_str} R18)"
                download_path_suffix += "_R18"
            else:
                url_template = "https://www.pixiv.net/ranking.php?mode=daily&p="
                pages_to_fetch = 10
                ranking_type_name = f"日榜 ({ranking_date_display_str} 全年龄)"
        elif selected_type == "周榜":
            ranking_date_display_str = current_zhou_str
            folder_date_str = current_week_str.replace('~', '_')
            download_path_suffix = f"Weekly/{folder_date_str}"
            if is_r18:
                url_template = "https://www.pixiv.net/ranking.php?mode=weekly_r18&p="
                pages_to_fetch = 3
                ranking_type_name = f"周榜 ({ranking_date_display_str} R18)"
                download_path_suffix += "_R18"
            else:
                url_template = "https://www.pixiv.net/ranking.php?mode=weekly&p="
                pages_to_fetch = 10
                ranking_type_name = f"周榜 ({ranking_date_display_str} 全年龄)"
        elif selected_type == "月榜":
            ranking_date_display_str = current_yue_str
            folder_date_str = current_yue_str.replace('年', '').replace('月', '')
            download_path_suffix = f"Monthly/{folder_date_str}"
            url_template = "https://www.pixiv.net/ranking.php?mode=monthly&p="
            pages_to_fetch = 10
            ranking_type_name = f"月榜 ({ranking_date_display_str})"
            if is_r18:
                self.append_log("注意: 月榜通常不区分R18/全年龄，此选项可能无效。")

        elif selected_type == "自定义日榜":
            custom_date, ok = QInputDialog.getText(self, "自定义日榜日期", "请输入自定义日期 (YYYYMMDD):",
                                                   QLineEdit.Normal, self.date_("day"))
            if not ok or not custom_date.isdigit() or len(custom_date) != 8:
                self.create_info_bar("请输入有效的自定义日期 (YYYYMMDD)。任务取消。", is_error=True)
                self.enabled_true()
                self.is_ranking_download_active = False
                return
            ranking_date_display_str = f"{custom_date[:4]}年{custom_date[4:6]}月{custom_date[6:]}日"
            folder_date_str = custom_date
            download_path_suffix = f"CustomDaily/{folder_date_str}"
            if is_r18:
                url_template = f"https://www.pixiv.net/ranking.php?mode=daily_r18&date={custom_date}&p="
                pages_to_fetch = 3
                ranking_type_name = f"自定义日榜 ({ranking_date_display_str} R18)"
                download_path_suffix += "_R18"
            else:
                url_template = f"https://www.pixiv.net/ranking.php?mode=daily&date={custom_date}&p="
                pages_to_fetch = 10
                ranking_type_name = f"自定义日榜 ({ranking_date_display_str} 全年龄)"

        elif selected_type == "新人排行榜":
            url_template = "https://www.pixiv.net/ranking.php?mode=rookie&p="
            pages_to_fetch = 6
            ranking_type_name = "新人排行榜"
            ranking_date_display_str = current_ri_str
            folder_date_str = current_folder_date
            download_path_suffix = f"Other/Rookie/{folder_date_str}"
            if is_r18: self.append_log("注意: 新人排行榜不区分R18/全年龄，此选项无效。")
        elif selected_type == "原创排行榜":
            url_template = "https://www.pixiv.net/ranking.php?mode=original&p="
            pages_to_fetch = 6
            ranking_type_name = "原创排行榜"
            ranking_date_display_str = current_ri_str
            folder_date_str = current_folder_date
            download_path_suffix = f"Other/Original/{folder_date_str}"
            if is_r18: self.append_log("注意: 原创排行榜不区分R18/全年龄，此选项无效。")
        elif selected_type == "受男性欢迎":
            if is_r18:
                url_template = "https://www.pixiv.net/ranking.php?mode=male_r18&p="
                pages_to_fetch = 6
                ranking_type_name = "受男性欢迎R18"
                ranking_date_display_str = current_ri_str
                folder_date_str = current_folder_date
                download_path_suffix = f"Other/Male_R18/{folder_date_str}"
            else:
                url_template = "https://www.pixiv.net/ranking.php?mode=male&p="
                pages_to_fetch = 10
                ranking_type_name = "受男性欢迎"
                ranking_date_display_str = current_ri_str
                folder_date_str = current_folder_date
                download_path_suffix = f"Other/Male/{folder_date_str}"
        elif selected_type == "受女性欢迎":
            if is_r18:
                url_template = "https://www.pixiv.net/ranking.php?mode=female_r18&p="
                pages_to_fetch = 6
                ranking_type_name = "受女性欢迎R18"
                ranking_date_display_str = current_ri_str
                folder_date_str = current_folder_date
                download_path_suffix = f"Other/Female_R18/{folder_date_str}"
            else:
                url_template = "https://www.pixiv.net/ranking.php?mode=female&p="
                pages_to_fetch = 10
                ranking_type_name = "受女性欢迎"
                ranking_date_display_str = current_ri_str
                folder_date_str = current_folder_date
                download_path_suffix = f"Other/Female/{folder_date_str}"

        base_download_root = get_config().get('download_path', {}).get('base_path', './downloads')
        full_ranking_dir = os.path.join(base_download_root, 'Ranking', download_path_suffix)
        self.current_ranking_metadata_path = full_ranking_dir
        self.current_ranking_type_name = ranking_type_name
        self.current_ranking_date_str = ranking_date_display_str

        metadata_filename = f"{folder_date_str}"
        if is_r18 and "R18" in ranking_type_name:
            metadata_filename += "_R18"
        metadata_filename += ".json"

        # meta_file_path = os.path.join(full_ranking_dir, metadata_filename)

        # if os.path.exists(meta_file_path):
        #     self.append_log(f"该排行榜【{ranking_type_name}】已下载，跳过本次任务。")
        #     self.create_info_bar(f"排行榜【{ranking_type_name}】已存在，跳过下载。", is_error=False)
        #     self.enabled_true()
        #     self.is_ranking_download_active = False
        #     return

        # self.append_log(f"开始获取 {ranking_type_name} 作品ID...")
        self.ranking_fetcher_thread = RankingFetcherThread(
            url_template, pages_to_fetch, ranking_type_name, ranking_date_display_str, download_path_suffix
        )
        self.ranking_fetcher_thread.progress_signal.connect(self.on_ranking_fetch_progress)
        self.ranking_fetcher_thread.ids_fetched.connect(self.on_ranking_fetch_finished)
        self.ranking_fetcher_thread.error_signal.connect(self.create_info_bar)
        self.ranking_fetcher_thread.start()

    def on_ranking_fetch_progress(self, message, speed):
        self.append_log(message)
        self.speed_label.setText(f"速度: {speed}")

    def on_ranking_fetch_finished(self, illust_ids, download_path_suffix, ranking_type_name, ranking_date_str):
        self.enabled_true()
        if not illust_ids:
            self.append_log("未获取到任何作品ID，任务结束。")
            self.is_ranking_download_active = False
            return

        self.append_log(f"作品ID获取完成，共 {len(illust_ids)} 个作品。")

        illust_ids_to_download = illust_ids

        self.total_illusts_for_current_ranking = len(illust_ids_to_download)
        self.completed_illusts_for_current_ranking = 0

        if self.total_illusts_for_current_ranking == 0:
            self.append_log("没有作品需要下载。任务结束。")
            self.is_ranking_download_active = False
            self._save_ranking_metadata()
            return

        # self.append_log(f"将下载 {self.total_illusts_for_current_ranking} 个作品。")

        full_ranking_dir = self.current_ranking_metadata_path

        for illust_id in illust_ids_to_download:
            list_item = QListWidgetItem(illust_id)
            list_item.setData(Qt.UserRole, illust_id)
            self.download_list_widget.addItem(list_item)
            self._download_item_map[illust_id] = list_item

            download_manager.add_task(
                item_id=illust_id,
                catalog='Ranking',
                item_type='illust',
                custom_path=full_ranking_dir,
                ranking_type_name=ranking_type_name,
                ranking_date_str=ranking_date_str,
                existing_image_ids=None
            )
            self.current_ranking_illust_ids.add(illust_id)

        self.append_log(f"已将 {self.total_illusts_for_current_ranking} 个作品添加到下载队列。")
        self.pause_resume_btn.setEnabled(True)
        self.stop_all_btn.setEnabled(True)


    def on_download_progress(self, item_id, completed, total, status, catalog): # 接收 catalog 参数
        # 仅处理 Ranking 类型的进度信息
        if catalog != 'Ranking':
            return

        # Filter out granular messages for logging
        if "正在获取详情" in status or "正在创建目录" in status or "正在下载图片" in status:
            return

        self.append_log(f"【{item_id}】 {status}")


    def on_download_finished(self, item_id, catalog): # 接收 catalog 参数
        # 仅处理 Ranking 类型的完成信息
        if catalog != 'Ranking':
            return

        # Remove item from UI list and map immediately upon completion
        if item_id in self._download_item_map:
            list_item = self._download_item_map.pop(item_id)
            row = self.download_list_widget.row(list_item)
            if row != -1:
                self.download_list_widget.takeItem(row)
            # self.append_log(f"【{item_id}】下载任务已结束。")

            if item_id in self.current_ranking_illust_ids:
                self.completed_illusts_for_current_ranking += 1
                self.current_ranking_downloaded_ids.add(item_id)

                self.append_log(f"排行榜下载进度: {self.completed_illusts_for_current_ranking}/{self.total_illusts_for_current_ranking}")

                if self.completed_illusts_for_current_ranking >= self.total_illusts_for_current_ranking:
                    self.append_log(f"【{self.current_ranking_type_name}】所有作品下载完成！")
                    self._save_ranking_metadata()
                    self.is_ranking_download_active = False
                    self.enabled_true()


    def _save_ranking_metadata(self):
        if not self.current_ranking_metadata_path:
            self.append_log("元数据保存失败: 无法确定排行榜保存路径。")
            return

        all_downloaded_ids = self.current_ranking_downloaded_ids
        try:
            sorted_all_downloaded_ids = sorted(list(all_downloaded_ids), key=lambda x: int(x))
        except ValueError:
            sorted_all_downloaded_ids = sorted(list(all_downloaded_ids))

        meta = {
            "ranking_type": self.current_ranking_type_name,
            "ranking_date": self.current_ranking_date_str,
            "quantity": len(sorted_all_downloaded_ids),
            "image_id": sorted_all_downloaded_ids,
            "download_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "base_path": os.path.abspath(self.current_ranking_metadata_path),
            "pid_option": get_config().get('download_path', {}).get('pid_option', '无')
        }

        folder_date_for_meta = ""
        if "日榜" in self.current_ranking_type_name or "新人" in self.current_ranking_type_name or \
           "原创" in self.current_ranking_type_name or "欢迎" in self.current_ranking_type_name:
            folder_date_for_meta = self.current_ranking_date_str.replace('年', '').replace('月', '').replace('日', '')
        elif "周榜" in self.current_ranking_type_name:
            folder_date_for_meta = self.current_ranking_date_str.replace('年', '').replace('月', '').replace('日', '').replace('~', '_')
        elif "月榜" in self.current_ranking_type_name:
            folder_date_for_meta = self.current_ranking_date_str.replace('年', '').replace('月', '')

        metadata_filename = f"{folder_date_for_meta}"
        if self.r18_toggle.isChecked() and "R18" in self.current_ranking_type_name:
             metadata_filename += "_R18"
        metadata_filename += ".json"

        meta_path = os.path.join(self.current_ranking_metadata_path, metadata_filename)
        try:
            os.makedirs(os.path.dirname(meta_path), exist_ok=True)
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self.append_log(f"【{self.current_ranking_type_name}】元数据保存成功: {meta_path}")
        except Exception as e:
            self.append_log(f"【{self.current_ranking_type_name}】元数据保存失败: {e}")

        self.current_ranking_illust_ids.clear()
        self.current_ranking_downloaded_ids.clear()
        self.current_ranking_metadata_path = None
        self.current_ranking_type_name = None
        self.current_ranking_date_str = None
        self.total_illusts_for_current_ranking = 0
        self.completed_illusts_for_current_ranking = 0


    def update_thread_count(self, count):
        self.thread_info_label.setText(f"线程: {count}")

    def update_proxy_info(self, proxy_info_str):
        self.proxy_info_label.setText(f"代理: {proxy_info_str}")

    def update_status_bar(self, config_obj=None):
        config = config_obj if config_obj else get_config()
        p = config.get('proxy', {});
        t, a, p_ = p.get('type', '0'), p.get('address', ''), p.get('port', '')
        proxy_info = "系统代理" if t == '0' else (
            f"HTTP: {a}:{p_}" if t == '1' else (f"SOCKS5: {a}:{p_}" if t == '2' else "未设置"))
        self.proxy_info_label.setText(f"代理: {proxy_info}")
        self.thread_info_label.setText(f"线程: {config.get('thread_count', 'N/A')}")
        self.cookie_info_label.setText(f"账号: {len(config.get('Accounts', {}))}")

    def update_speed_display(self, speed_bytes_per_sec):
        if speed_bytes_per_sec > 1024 * 1024:
            speed_text = f"{speed_bytes_per_sec / (1024 * 1024):.2f} MB/s"
        elif speed_bytes_per_sec > 1024:
            speed_text = f"{speed_bytes_per_sec / 1024:.1f} KB/s"
        else:
            # 只有当没有活跃或排队的任务时才显示 0 KB/s
            if not download_manager.get_active_and_queued_tasks():
                speed_text = "0 KB/s"
            else:
                speed_text = f"{int(speed_bytes_per_sec)} B/s"
        self.speed_label.setText(f"速度: {speed_text}")

    def create_info_bar(self, message, is_error=False):
        if is_error:
            InfoBar.error(
                title="错误",
                content=message,
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000
            )
        else:
            InfoBar.success(
                title="提示",
                content=message,
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000
            )

    def append_log(self, message):
        self.log_output.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}");
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def show_log_context_menu(self, pos):
        menu = RoundMenu(parent=self.log_output)

        # Only log specific actions
        select_all_action = Action(FIF.BASKETBALL, '全选');
        select_all_action.triggered.connect(self.log_output.selectAll)
        copy_action = Action(FIF.COPY, '复制');
        copy_action.triggered.connect(self.log_output.copy)
        clear_action = Action(FIF.DELETE, '清空');
        clear_action.triggered.connect(self.log_output.clear)
        menu.addAction(select_all_action)
        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction(clear_action)
        menu.exec(self.log_output.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)

    # 3. 新增 show_blank_area_context_menu 方法
    def show_blank_area_context_menu(self, pos):
        """
        显示空白区域的右键菜单。
        """
        menu = RoundMenu(parent=self) # 菜单的父对象是 Ranking 窗口本身
        action = Action(FIF.FOLDER, '打开下载目录')
        action.triggered.connect(self.open_download_directory)
        menu.addAction(action)
        action = Action(FIF.APPLICATION, '打开软件目录')
        action.triggered.connect(self.open_software_directory)
        menu.addAction(action)
        menu.exec(self.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)

    def open_download_directory(self):
        try:
            path = get_config().get('download_path', {}).get('base_path', './downloads')
            abs_path = os.path.abspath(path) + '/Ranking' # Changed path to /Ranking
            os.makedirs(abs_path, exist_ok=True)
            os.startfile(abs_path)
        except Exception as e:
            self.create_info_bar(f"无法打开目录: {e}", is_error=True)

    def open_software_directory(self):
        try:
            os.startfile(os.getcwd())
        except Exception as e:
            self.create_info_bar(f"无法打开目录: {e}", is_error=True)

    def show_download_list_context_menu(self, pos):
        if item := self.download_list_widget.itemAt(pos):
            illust_id = item.data(Qt.UserRole)
            if not illust_id:
                illust_id = item.text().split(' ')[0]

            menu = RoundMenu(parent=self.download_list_widget)

            action_delete = Action(FIF.DELETE, '从列表删除')
            action_delete.triggered.connect(lambda: self.delete_list_item(item))
            menu.addAction(action_delete)

            menu.exec(self.download_list_widget.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)

    def toggle_pause_resume_all_ranking(self):
        if self.is_ranking_paused:
            download_manager.resume_all_ranking_downloads()
            self.is_ranking_paused = False
            self.pause_resume_btn.setText("暂停下载")
            self.pause_resume_btn.setIcon(FIF.PAUSE)
            self.append_log("已恢复所有排行榜下载任务。")
            self.create_info_bar("所有排行榜下载任务已恢复。")
        else:
            download_manager.pause_all_ranking_downloads()
            self.is_ranking_paused = True
            self.pause_resume_btn.setText("继续下载")
            self.pause_resume_btn.setIcon(FIF.PLAY)
            self.append_log("已暂停所有排行榜下载任务。")
            self.create_info_bar("所有排行榜下载任务已暂停。")

    def _stop_all_ranking_tasks(self):
        download_manager.stop_all_ranking_downloads()
        self.append_log("已停止所有排行榜下载任务并清空列表。")
        self.create_info_bar("所有排行榜下载任务已停止。")
        self.download_list_widget.clear()
        self._download_item_map.clear()
        self.current_ranking_illust_ids.clear()
        self.current_ranking_downloaded_ids.clear()
        self.current_ranking_metadata_path = None
        self.current_ranking_type_name = None
        self.current_ranking_date_str = None
        self.total_illusts_for_current_ranking = 0
        self.completed_illusts_for_current_ranking = 0
        self.is_ranking_download_active = False
        self.is_ranking_paused = False
        self.pause_resume_btn.setText("暂停下载")
        self.pause_resume_btn.setIcon(FIF.PAUSE)
        self.enabled_true()


    def delete_list_item(self, item):
        illust_id = item.data(Qt.UserRole)
        if not illust_id:
            illust_id = item.text().split(' ')[0]

        if download_manager.is_task_queued_or_active(illust_id):
            download_manager.stop_download(illust_id)
            self.append_log(f"已停止并从列表移除作品: {illust_id}")
        else:
            row = self.download_list_widget.row(item)
            if row != -1:
                self.download_list_widget.takeItem(row)
            self._download_item_map.pop(illust_id, None)
            self.append_log(f"已从列表移除作品: {illust_id}")

        if illust_id in self.current_ranking_illust_ids:
            self.current_ranking_illust_ids.remove(illust_id)
            self.total_illusts_for_current_ranking = len(self.current_ranking_illust_ids)
            self.append_log(f"排行榜剩余任务数更新: {self.total_illusts_for_current_ranking - self.completed_illusts_for_current_ranking}")
            if self.completed_illusts_for_current_ranking >= self.total_illusts_for_current_ranking:
                self.append_log(f"【{self.current_ranking_type_name}】所有作品下载完成！")
                self._save_ranking_metadata()
                self.is_ranking_download_active = False
                self.enabled_true()

    def enabled_false(self):
        self.ranking_type_combo.setEnabled(False)
        self.start_download_btn.setEnabled(False)
        self.r18_toggle.setEnabled(False)
        self.pause_resume_btn.setEnabled(False)
        self.stop_all_btn.setEnabled(False)

    def enabled_true(self):
        self.ranking_type_combo.setEnabled(True)
        self.start_download_btn.setEnabled(True)
        self.r18_toggle.setEnabled(True)
        if download_manager.get_active_and_queued_ranking_tasks():
            self.pause_resume_btn.setEnabled(True)
            self.stop_all_btn.setEnabled(True)
        else:
            self.pause_resume_btn.setEnabled(False)
            self.stop_all_btn.setEnabled(False)
            self.is_ranking_paused = False
            self.pause_resume_btn.setText("暂停下载")
            self.pause_resume_btn.setIcon(FIF.PAUSE)

        self.is_ranking_download_active = False

    def config_initial(self):
        pass

    def date_(self, text):
        if text == "day":
            return datetime.datetime.now().strftime("%Y%m%d")
        elif text == "ri":
            return datetime.datetime.now().strftime("%Y年%m月%d日")
        elif text == "folder_date":
            return datetime.datetime.now().strftime("%Y%m%d")
        elif text == "week":
            today = datetime.date.today()
            start_of_week = today - datetime.timedelta(days=today.weekday())
            end_of_week = start_of_week + datetime.timedelta(days=6)
            return f"{start_of_week.strftime('%Y%m%d')}~{end_of_week.strftime('%Y%m%d')}"
        elif text == "zhou":
            today = datetime.date.today()
            start_of_week = today - datetime.timedelta(days=today.weekday())
            end_of_week = start_of_week + datetime.timedelta(days=6)
            return f"{start_of_week.strftime('%Y年%m月%d日')}~{end_of_week.strftime('%Y年%m月%d日')}"
        elif text == "month":
            today = datetime.date.today()
            first_day_of_month = today.replace(day=1)
            last_day_of_month = (first_day_of_month + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
            return f"{first_day_of_month.strftime('%Y%m%d')}~{last_day_of_month.strftime('%Y%m%d')}"
        elif text == "yue":
            return datetime.datetime.now().strftime("%Y年%m月")

