# app/user.py

import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QLabel, QFrame, QSizePolicy, QListWidgetItem
)
from qfluentwidgets import (
    RoundMenu, Action, MenuAnimationType, FluentIcon as FIF, InfoBar, InfoBarPosition,
    ListWidget, TextEdit
)
from PyQt5.QtCore import Qt, QEvent, QPoint
from PyQt5.QtGui import QPixmap, QIcon
import json
import os
import datetime
import re
import requests

from .download import download_manager, cookie_manager
from .config_manager import config_manager, get_config
from .history_manager import history_manager


class User(QWidget):
    # Define fixed colors for left and right borders
    LEFT_BORDER_COLOR = "#e483fa"
    RIGHT_BORDER_COLOR = "#4bbeff"

    # Define uniform border thickness and corner radius
    BORDER_THICKNESS = 3
    COMMON_BORDER_RADIUS = 9


    # Define gradient background QSS string
    GRADIENT_BACKGROUND_QSS = f"""
        qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {LEFT_BORDER_COLOR}, stop:1 {RIGHT_BORDER_COLOR})
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_paused = False
        self.current_downloading_uid = None

        self.initUI()
        self.connect_signals()

        self.update_status_bar()
        self.append_log("用户界面初始化完成。")
        QApplication.instance().installEventFilter(self)
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
            logo_label.setText("Pixiv用户下载")
            logo_label.setStyleSheet(
                "font-size: 32px; color: #00A1D6; font-weight: bold;")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setStyleSheet("margin-bottom: 20px;")

        # --- Search Input Section (using three nested QFrame for complex border) ---
        border_thickness = self.BORDER_THICKNESS
        common_border_radius = self.COMMON_BORDER_RADIUS
        original_lineedit_height = 45

        search_input_outer_gradient_frame = QFrame(self)
        search_input_outer_gradient_frame.setObjectName("searchInputOuterGradientFrame")
        search_input_outer_gradient_frame.setStyleSheet(
            f"""
            #searchInputOuterGradientFrame {{
                background: {self.GRADIENT_BACKGROUND_QSS};
                border-radius: {common_border_radius}px;
                border: none;
            }}
            """
        )

        search_input_middle_solid_frame = QFrame(search_input_outer_gradient_frame)
        search_input_middle_solid_frame.setObjectName("searchInputMiddleSolidFrame")
        search_input_middle_solid_frame.setStyleSheet(
            f"""
            #searchInputMiddleSolidFrame {{
                background-color: transparent;
                border-radius: {common_border_radius}px;
                border-left: {border_thickness}px solid {self.LEFT_BORDER_COLOR};
                border-right: {border_thickness}px solid {self.RIGHT_BORDER_COLOR};
            }}
            """
        )
        # 移除此行：search_input_middle_solid_frame.setFixedHeight(original_lineedit_height)

        search_input_inner_white_frame = QFrame(search_input_middle_solid_frame)
        search_input_inner_white_frame.setObjectName("searchInputInnerWhiteFrame")
        search_input_inner_white_frame.setStyleSheet(
            f"""
            #searchInputInnerWhiteFrame {{
                background-color: white;
                border-radius: {common_border_radius - border_thickness}px;
                border: none;
            }}
            """
        )
        # 移除此行：search_input_inner_white_frame.setFixedHeight(original_lineedit_height)

        self.search_input = QLineEdit(search_input_inner_white_frame)
        self.search_input.setObjectName("searchLineEdit")
        self.search_input.setPlaceholderText("请输入用户UID")
        self.search_input.setFixedHeight(original_lineedit_height)
        self.search_input.setAlignment(Qt.AlignCenter)
        self.search_input.setContextMenuPolicy(Qt.CustomContextMenu)

        self.search_input.setStyleSheet(
            f"""
            #searchLineEdit {{
                border: none;
                background-color: transparent;
                padding: 0 80px;
                font: 28px 'Segoe UI', 'Microsoft YaHei';
            }}
            #searchLineEdit:focus {{
            }}
            """
        )

        btn_layout = QHBoxLayout(self.search_input)
        btn_layout.setContentsMargins(0, 0, 5, 0)
        btn_layout.addStretch()
        btn_style = "QPushButton { background-color: transparent; border: none; } QPushButton:hover { background-color: rgba(0, 0, 0, 0.05); border-radius: 5px;}"

        self.toggle_func_btn = QPushButton()
        self.toggle_func_btn.setIcon(QIcon(FIF.UP.path()))
        self.toggle_func_btn.setFixedSize(35, 35)
        self.toggle_func_btn.setStyleSheet(btn_style)

        self.history_btn = QPushButton()
        self.history_btn.setIcon(QIcon(FIF.HISTORY.path()))
        self.history_btn.setFixedSize(35, 35)
        self.history_btn.setStyleSheet(btn_style)

        btn_layout.addWidget(self.toggle_func_btn)
        btn_layout.addWidget(self.history_btn)

        # Layout nesting: QLineEdit -> inner_white_frame -> middle_solid_frame -> outer_gradient_frame
        inner_white_frame_layout = QHBoxLayout(search_input_inner_white_frame)
        inner_white_frame_layout.setContentsMargins(0, 0, 0, 0)
        inner_white_frame_layout.addWidget(self.search_input)
        search_input_inner_white_frame.setLayout(inner_white_frame_layout)

        middle_solid_frame_layout = QHBoxLayout(search_input_middle_solid_frame)
        middle_solid_frame_layout.setContentsMargins(0, 0, 0, 0)
        middle_solid_frame_layout.addWidget(search_input_inner_white_frame)
        search_input_middle_solid_frame.setLayout(middle_solid_frame_layout)

        outer_gradient_frame_layout = QHBoxLayout(search_input_outer_gradient_frame)
        outer_gradient_frame_layout.setContentsMargins(0, border_thickness, 0, border_thickness)
        outer_gradient_frame_layout.addWidget(search_input_middle_solid_frame)
        search_input_outer_gradient_frame.setLayout(outer_gradient_frame_layout)

        # Crucial: Create a horizontal layout to wrap search_input_outer_gradient_frame for adaptive width and centering
        search_bar_h_layout = QHBoxLayout()
        search_bar_h_layout.setContentsMargins(0, 0, 0, 0)
        search_bar_h_layout.addStretch(1)
        search_bar_h_layout.addWidget(search_input_outer_gradient_frame, 5)
        search_bar_h_layout.addStretch(1)

        search_container = QWidget(self)
        search_layout = QVBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        search_layout.addLayout(search_bar_h_layout)

        self.func_container = QWidget(self)
        self.func_container.hide()
        func_layout = QHBoxLayout(self.func_container)
        func_layout.setContentsMargins(0, 15, 0, 0)
        func_layout.addStretch(1)
        inner_func = QWidget(self.func_container)
        inner_func_layout = QHBoxLayout(inner_func)
        inner_func_layout.setContentsMargins(0, 0, 0, 0)
        inner_func_layout.setSpacing(15)

        list_area, self.result_list = self.create_area_widget("下载列表", ListWidget)
        output_area, self.log_output = self.create_area_widget("操作日志", TextEdit)

        self.log_output.setReadOnly(True)

        inner_func_layout.addWidget(list_area, 3)
        inner_func_layout.addWidget(output_area, 17)
        func_layout.addWidget(inner_func, 5)
        func_layout.addStretch(1)

        search_layout.addWidget(self.func_container, 9)
        search_layout.addStretch()

        # --- History List Section (using QFrame+padding) ---
        self.history_list_outer_container = QFrame(self)
        self.history_list_outer_container.setObjectName("historyListOuterContainer")
        self.history_list_outer_container.setStyleSheet(
            f"""
            #historyListOuterContainer {{
                background: {self.GRADIENT_BACKGROUND_QSS};
                border-radius: {self.COMMON_BORDER_RADIUS}px;
                padding: {self.BORDER_THICKNESS}px;
            }}
            """
        )
        history_list_layout = QVBoxLayout(self.history_list_outer_container)
        history_list_layout.setContentsMargins(0, 0, 0, 0)

        self.history_list = ListWidget(self.history_list_outer_container)
        self.history_list.setObjectName("historyListInnerWidget")
        self.history_list.setStyleSheet(
            f"""
            #historyListInnerWidget {{
                border: none;
                border-radius: {self.COMMON_BORDER_RADIUS - self.BORDER_THICKNESS}px;
                background-color: white;
            }}
            #historyListInnerWidget::item {{
                padding: 10px;
                border-bottom: 1px solid #e0e0e0;
                font: 14px 'Segoe UI', 'Microsoft YaHei';
            }}
            #historyListInnerWidget::item:hover {{ background-color: rgba(0, 161, 214, 0.1); }}
            #historyListInnerWidget::item:selected {{ background-color: rgba(0, 161, 214, 0.2); color: black; }}
            """
        )
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        history_list_layout.addWidget(self.history_list)

        self.history_list_outer_container.hide()
        self.update_history_list()

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
        self.cookie_info_label = QLabel("账号: N/A")
        self.cookie_info_label.setStyleSheet(label_style)
        status_layout.addWidget(self.proxy_info_label)
        status_layout.addWidget(self.thread_info_label)
        status_layout.addWidget(self.speed_label)
        status_layout.addStretch()
        status_layout.addWidget(self.cookie_info_label)

        main_layout.addStretch(1)
        main_layout.addWidget(logo_label)
        main_layout.addWidget(search_container, 9)
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

            log_middle_solid_frame = QFrame(log_outer_gradient_frame)
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

            log_inner_white_frame = QFrame(log_middle_solid_frame)
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
                }}
                """
            )

            inner_white_frame_layout = QVBoxLayout(log_inner_white_frame)
            inner_white_frame_layout.setContentsMargins(0, 0, 0, 0)
            inner_white_frame_layout.addWidget(content_widget)
            log_inner_white_frame.setLayout(inner_white_frame_layout)

            middle_solid_frame_layout = QVBoxLayout(log_middle_solid_frame)
            middle_solid_frame_layout.setContentsMargins(0, 0, 0, 0)
            middle_solid_frame_layout.addWidget(log_inner_white_frame)
            log_middle_solid_frame.setLayout(middle_solid_frame_layout)

            outer_gradient_frame_layout = QVBoxLayout(log_outer_gradient_frame)
            outer_gradient_frame_layout.setContentsMargins(0, border_thickness, 0, border_thickness)
            outer_gradient_frame_layout.addWidget(log_middle_solid_frame)
            log_outer_gradient_frame.setLayout(outer_gradient_frame_layout)

            main_layout.addWidget(log_outer_gradient_frame, 1)

        else:
            content_widget.setStyleSheet(
                f"""
                #{content_widget.objectName()} {{
                    border: {border_thickness}px solid {self.LEFT_BORDER_COLOR};
                    border-radius: {common_border_radius}px;
                    background-color: white;
                    font: 14px 'Segoe UI', 'Microsoft YaHei';
                    padding: 5px;
                }}
                QListWidget::item {{ padding: 5px; border-bottom: 1px solid #e0e0e0; }}
                QListWidget::item:hover {{ background-color: rgba(0, 161, 214, 0.1); }}
                QListWidget::item:selected {{ background-color: rgba(0, 161, 214, 0.2); color: black; }}
                """
            )
            main_layout.addWidget(content_widget, 1)

        return main_container, content_widget

    def connect_signals(self):
        self.search_input.returnPressed.connect(self.start_download_from_input)
        self.search_input.customContextMenuRequested.connect(self.show_search_input_context_menu)
        self.customContextMenuRequested.connect(self.show_blank_area_context_menu)

        if hasattr(self, 'toggle_func_btn'):
            self.toggle_func_btn.clicked.connect(self.toggle_func_area)
        else:
            print("Warning: toggle_func_btn not found during signal connection.")

        if hasattr(self, 'history_btn'):
            self.history_btn.clicked.connect(self.toggle_history)
        else:
            print("Warning: history_btn not found during signal connection.")

        self.history_list.itemClicked.connect(self.select_history)
        self.history_list.customContextMenuRequested.connect(self.show_history_list_context_menu)
        self.result_list.customContextMenuRequested.connect(self.show_result_list_context_menu)
        self.log_output.customContextMenuRequested.connect(self.show_log_output_context_menu)
        config_manager.config_changed.connect(self.update_status_bar)
        # 修改信号连接，槽函数需要接收新的 catalog 参数
        download_manager.task_progress.connect(self.on_task_progress)
        download_manager.task_finished.connect(self.on_task_finished)
        download_manager.speed_updated.connect(self.update_speed_display)

    def start_download_from_input(self):
        if not self.func_container.isVisible(): self.toggle_func_area()
        uid = self.search_input.text().strip()
        if not uid.isdigit(): self.create_info_bar("请输入有效的用户UID", is_error=True); return

        for i in range(self.result_list.count()):
            if self.result_list.item(i).text() == uid:
                self.create_info_bar(f"任务 {uid} 已在列表中", is_error=True);
                return

        item = QListWidgetItem(uid)
        item.setData(Qt.UserRole, {'existing_ids': None, 'strategy': 'default'})
        self.result_list.addItem(item)

        self.append_log(f"添加任务: {uid}") # 用户下载没有年龄模式
        if self.current_downloading_uid is None:
            self.start_next_download()

        history_manager.add_record('user', uid)
        self.update_history_list()
        self.history_list_outer_container.hide()

    def start_next_download(self):
        if self.result_list.count() > 0:
            current_item = self.result_list.item(0)
            self.current_downloading_uid = current_item.text()
            download_data = current_item.data(Qt.UserRole)

            existing_ids = download_data.get('existing_ids') if download_data else None
            strategy = download_data.get('strategy') if download_data else 'default'

            self.is_paused = False
            self.append_log(f"开始下载任务: {self.current_downloading_uid} (策略: {strategy})")
            download_manager.add_task(
                item_id=self.current_downloading_uid,
                catalog='User',
                item_type='user',
                existing_image_ids=existing_ids,
                completion_strategy=strategy
            )
        else:
            self.current_downloading_uid = None
            self.is_paused = False

    def on_task_progress(self, item_id, completed, total, status, catalog): # 接收 catalog 参数
        # 仅处理 User 类型的进度信息
        if catalog != 'User':
            return
        if item_id == self.current_downloading_uid:
            self.append_log(f"【{item_id}】 {status}")

    def on_task_finished(self, item_id, catalog): # 接收 catalog 参数
        # 仅处理 User 类型的完成信息
        if catalog != 'User':
            return
        if item_id == self.current_downloading_uid:
            self.append_log(f"【{item_id}】下载任务已结束。");
            self.remove_item_from_list(item_id);
            self.start_next_download()

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

    def remove_item_from_list(self, item_id):
        for i in range(self.result_list.count()):
            if self.result_list.item(i).text() == item_id: self.result_list.takeItem(i); break

    def show_search_input_context_menu(self, pos):
        menu = RoundMenu(parent=self.search_input)
        if self.is_paused:
            action = Action(FIF.PLAY, '继续下载');
            action.triggered.connect(self.resume_download);
            menu.addAction(action)
        elif self.current_downloading_uid:
            action = Action(FIF.PAUSE, '暂停下载');
            action.triggered.connect(self.pause_download);
            menu.addAction(action)
        else:
            action = Action(FIF.DOWNLOAD, '开始下载');
            action.triggered.connect(self.start_download_from_input);
            menu.addAction(action)

        # --- Completion Download Sub-menu ---
        completion_menu = RoundMenu(parent=menu)
        completion_menu.setTitle('补全下载')
        completion_menu.setIcon(FIF.SYNC)

        default_completion_action = Action(FIF.SYNC, '默认补全')
        default_completion_action.triggered.connect(lambda: self.start_completion_download(strategy='default'))
        completion_menu.addAction(default_completion_action)

        smart_completion_action = Action(FIF.SYNC, '新作补全')
        smart_completion_action.triggered.connect(lambda: self.start_completion_download(strategy='smart'))
        completion_menu.addAction(smart_completion_action)

        menu.addMenu(completion_menu)
        menu.exec(self.search_input.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)

    def show_blank_area_context_menu(self, pos):
        """
        显示空白区域的右键菜单。
        """
        menu = RoundMenu(parent=self)
        action = Action(FIF.FOLDER, '打开下载目录')
        action.triggered.connect(self.open_download_directory)
        menu.addAction(action)
        action = Action(FIF.APPLICATION, '打开软件目录')
        action.triggered.connect(self.open_software_directory)
        menu.addAction(action)
        menu.exec(self.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)


    def pause_download(self):
        if self.current_downloading_uid:
            download_manager.pause_download(self.current_downloading_uid)
            self.is_paused = True
            self.append_log(f"【{self.current_downloading_uid}】下载已暂停。")

    def resume_download(self):
        if self.current_downloading_uid:
            download_manager.resume_download(self.current_downloading_uid)
            self.is_paused = False
            self.append_log(f"【{self.current_downloading_uid}】下载已恢复。")

    def stop_download(self):
        if self.current_downloading_uid:
            download_manager.stop_download(self.current_downloading_uid)

    def open_download_directory(self):
        try:
            path = get_config().get('download_path', {}).get('base_path', './downloads')
            abs_path = os.path.abspath(path) + '/User'
            os.makedirs(abs_path, exist_ok=True)
            os.startfile(abs_path)
        except Exception as e:
            self.create_info_bar(f"无法打开目录: {e}", is_error=True)

    def open_software_directory(self):
        try:
            os.startfile(os.getcwd())
        except Exception as e:
            self.create_info_bar(f"无法打开目录: {e}", is_error=True)

    def show_result_list_context_menu(self, pos):
        if item := self.result_list.itemAt(pos):
            menu = RoundMenu(parent=self.result_list)
            action = Action(FIF.DELETE, '删除')
            action.triggered.connect(lambda: self.delete_list_item(item))
            menu.addAction(action)
            menu.exec(self.result_list.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)

    def delete_list_item(self, item):
        uid = item.text()
        if uid == self.current_downloading_uid:
            download_manager.stop_download(uid)
        self.result_list.takeItem(self.result_list.row(item));
        self.append_log(f"已从列表移除任务: {uid}")

    def show_history_list_context_menu(self, pos):
        if item := self.history_list.itemAt(pos):
            if item.text() == "--- 清除搜索历史 ---":
                clear_all_action = Action(FIF.CLEAR_SELECTION, '清空所有历史记录');
                clear_all_action.triggered.connect(self.clear_search_history)
                self.show_context_menu(self.history_list, [clear_all_action], pos)
            else:
                delete_action = Action(FIF.DELETE, '删除此项');
                delete_action.triggered.connect(lambda: self.delete_history_item(item))
                clear_all_action = Action(FIF.CLEAR_SELECTION, '清空所有历史记录');
                clear_all_action.triggered.connect(self.clear_search_history)
                self.show_context_menu(self.history_list, [delete_action, "separator", clear_all_action], pos)

    def show_log_output_context_menu(self, pos):
        select_all_action = Action(FIF.BASKETBALL, '全选');
        select_all_action.triggered.connect(self.log_output.selectAll)
        copy_action = Action(FIF.COPY, '复制');
        copy_action.triggered.connect(self.log_output.copy)
        clear_action = Action(FIF.DELETE, '清空');
        clear_action.triggered.connect(self.log_output.clear)
        self.show_context_menu(self.log_output, [select_all_action, copy_action, "separator", clear_action], pos)

    def delete_history_item(self, item):
        record = item.data(Qt.UserRole)
        if record and 'type' in record and 'id' in record:
            item_type = record['type']
            item_id = record['id']
            if history_manager.delete_record(item_type, item_id):
                self.update_history_list()
                self.create_info_bar("已删除历史记录")
            else:
                self.create_info_bar("删除历史记录失败。", is_error=True)
        else:
            self.create_info_bar("无法识别的历史记录项。", is_error=True)

    def clear_search_history(self):
        history_manager.clear_all_history()
        self.update_history_list()
        self.create_info_bar("搜索历史已清除")

    def show_context_menu(self, widget, actions, pos):
        menu = RoundMenu(parent=widget)
        for action in actions:
            if action == "separator":
                menu.addSeparator()
            else:
                menu.addAction(action)
        menu.exec(widget.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)

    def append_log(self, message):
        self.log_output.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}");
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def toggle_func_area(self):
        is_visible = not self.func_container.isVisible()
        self.func_container.setVisible(is_visible)
        self.toggle_func_btn.setIcon(QIcon(FIF.UP.path() if is_visible else FIF.DOWN.path()))

    def toggle_history(self):
        if self.history_list_outer_container.isVisible():
            self.history_list_outer_container.hide()
        else:
            self.position_history_list();
            self.history_list_outer_container.show();
            self.history_list_outer_container.raise_()

    def position_history_list(self):
        global_pos = self.search_input.mapToGlobal(self.search_input.rect().bottomLeft())
        pos_in_user = self.mapFromGlobal(global_pos)

        self.history_list_outer_container.move(pos_in_user.x() - 3, pos_in_user.y() + 1)

        search_input_outer_gradient_frame = self.findChild(QFrame, "searchInputOuterGradientFrame")
        if search_input_outer_gradient_frame:
            self.history_list_outer_container.setFixedWidth(search_input_outer_gradient_frame.width())
        else:
            self.history_list_outer_container.setFixedWidth(self.search_input.width())

        records = history_manager.get_history_records(filter_type='user')
        item_count = len(records)

        if item_count == 0:
            self.history_list_outer_container.hide();
            return

        # 如果有历史记录，则会有一个额外的“清除搜索历史”条目
        effective_item_count = item_count + 1

        item_height = 45;
        max_height = 250

        calculated_inner_height = min(effective_item_count * item_height, max_height - 2 * self.BORDER_THICKNESS)
        if calculated_inner_height < 0: calculated_inner_height = 0

        self.history_list.setFixedHeight(calculated_inner_height)

        self.history_list_outer_container.setFixedHeight(calculated_inner_height + 2 * self.BORDER_THICKNESS)

    def update_history_list(self):
        self.history_list.clear();
        records = history_manager.get_history_records(filter_type='user')
        for record in records:
            item_text = f"[{record.get('timestamp', 'N/A')}] {record.get('id', 'N/A')}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, record)
            self.history_list.addItem(item)

        if records:
            self.history_list.addItem("--- 清除搜索历史 ---")

    def select_history(self, item):
        text = item.text()
        if text == "--- 清除搜索历史 ---":
            self.clear_search_history();
            self.history_list_outer_container.hide();
            return

        record = item.data(Qt.UserRole)
        if record and 'id' in record:
            self.search_input.setText(record['id'])
        else:
            uid_match = re.match(r'\[.*?\]\s*(\d+)', text)
            if uid_match:
                uid_name = uid_match.group(1)
                self.search_input.setText(uid_name)
            else:
                self.search_input.setText(text.split("] ", 1)[-1])

        self.history_list_outer_container.hide()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonPress and self.history_list_outer_container.isVisible():
            if not self.history_list_outer_container.rect().contains(
                    self.history_list_outer_container.mapFromGlobal(e.globalPos())):
                self.history_list_outer_container.hide()
        return super().eventFilter(obj, e)

    def create_info_bar(self, text, is_error=False):
        (InfoBar.error if is_error else InfoBar.success)(title='提示', content=text, isClosable=True,
                                                         position=InfoBarPosition.TOP, duration=2000, parent=self)

    # --- Completion download methods for Users ---
    def start_completion_download(self, strategy='default'):
        if not self.func_container.isVisible(): self.toggle_func_area()

        uid_input = self.search_input.text().strip()
        download_base_dir = get_config().get('download_path', {}).get('base_path', './downloads')
        user_download_dir = os.path.join(download_base_dir, 'User')

        os.makedirs(user_download_dir, exist_ok=True)

        if uid_input:
            if not uid_input.isdigit():
                self.create_info_bar("请输入有效的用户UID进行补全下载。", is_error=True)
                return

            user_specific_download_folder = os.path.join(user_download_dir, uid_input)
            json_file_path = os.path.join(user_specific_download_folder, f"{uid_input}.json")

            self._process_single_completion_download(uid_input, json_file_path, strategy)
        else:
            self.append_log(f"【补全下载】搜索框为空，开始遍历所有用户下载配置 (策略: {strategy})。")
            self._process_all_completion_downloads(user_download_dir, strategy)

    def _process_single_completion_download(self, uid, json_path, strategy):
        config_data = None
        existing_image_ids = []

        user_download_folder = os.path.dirname(json_path)

        if os.path.exists(json_path):
            config_data = self._read_user_json_config(json_path)
            if config_data:
                existing_image_ids = config_data.get('image_id', [])
                self.append_log(f"【补全下载】用户 {uid} 配置已加载：")
                self.append_log(f"  - image_id: {existing_image_ids}")
                self.append_log(f"  - base_path: {config_data.get('base_path', 'N/A')}")
            else:
                self.append_log(f"【补全下载】读取用户 {uid} 的配置文件失败，尝试从文件生成。")
                if os.path.isdir(user_download_folder):
                    generated_ids = self._generate_metadata_from_files(uid, user_download_folder, 'user')
                    if generated_ids is not None:
                        existing_image_ids = generated_ids
                        self.create_info_bar(f"已为用户 {uid} 生成配置文件。", is_error=False)
                    else:
                        self.create_info_bar(f"无法为用户 {uid} 生成配置文件，将进行常规下载。", is_error=True)
                        self.append_log(f"【补全下载】用户 {uid} 无配置文件且无法生成，按常规方式添加任务。")
                        self.start_download_from_input()
                        return
                else:
                    self.create_info_bar(f"用户 {uid} 的下载目录不存在，将进行常规下载。", is_error=False)
                    self.append_log(f"【补全下载】用户 {uid} 下载目录不存在，按常规方式添加任务。")
                    self.start_download_from_input()
                    return
        elif os.path.isdir(user_download_folder):
            generated_ids = self._generate_metadata_from_files(uid, user_download_folder, 'user')
            if generated_ids is not None:
                existing_image_ids = generated_ids
                self.create_info_bar(f"已为用户 {uid} 生成配置文件。", is_error=False)
            else:
                self.create_info_bar(f"无法为用户 {uid} 生成配置文件，将进行常规下载。", is_error=True)
                self.append_log(f"【补全下载】用户 {uid} 无配置文件且无法生成，按常规方式添加任务。")
                self.start_download_from_input()
                return
        else:
            self.create_info_bar(f"未找到用户 {uid} 的配置文件或下载目录，将进行常规下载。", is_error=False)
            self.append_log(f"【补全下载】未找到用户 {uid} 的配置文件或下载目录，按常规方式添加任务。")
            self.start_download_from_input()
            return

        for i in range(self.result_list.count()):
            if self.result_list.item(i).text() == uid:
                self.create_info_bar(f"任务 {uid} 已在列表中，无需重复添加。", is_error=True);
                return

        item = QListWidgetItem(uid)
        item.setData(Qt.UserRole, {'existing_ids': existing_image_ids, 'strategy': strategy})
        self.result_list.addItem(item)
        self.append_log(f"【补全下载】已将用户 {uid} 添加到下载列表。")

        if self.current_downloading_uid is None:
            self.start_next_download()

    def _process_all_completion_downloads(self, user_download_dir, strategy):
        found_users = set()
        self.append_log(f"【补全下载】开始扫描目录: {user_download_dir}")

        for item_name in os.listdir(user_download_dir):
            item_path = os.path.join(user_download_dir, item_name)
            if not os.path.isdir(item_path):
                continue

            uid_to_process = None
            existing_image_ids = []

            for fname in os.listdir(item_path):
                if fname.endswith('.json'):
                    current_json_path = os.path.join(item_path, fname)
                    config_data = self._read_user_json_config(current_json_path)
                    if config_data and config_data.get('user_id'):
                        uid_to_process = config_data['user_id']
                        existing_image_ids = config_data.get('image_id', [])
                        self.append_log(f"【补全下载】找到用户 {uid_to_process} 的配置文件: {current_json_path}")
                        break

            if uid_to_process is None:
                if item_name.isdigit():
                    uid_to_process = item_name
                    generated_ids = self._generate_metadata_from_files(uid_to_process, item_path, 'user')
                    if generated_ids is not None:
                        existing_image_ids = generated_ids
                        self.append_log(f"【补全下载】已为用户 {uid_to_process} 从文件生成配置文件。")
                    else:
                        self.append_log(f"【补全下载】警告: 无法为用户 {uid_to_process} 生成配置文件，跳过。")
                        continue
                else:
                    self.append_log(
                        f"【补全下载】警告: 用户目录 '{item_name}' 无UID配置文件且无法自动生成 (非数字目录名)，跳过。")
                    continue

            if uid_to_process is None:
                continue

            for i in range(self.result_list.count()):
                if self.result_list.item(i).text() == uid_to_process:
                    self.append_log(f"【补全下载】任务 {uid_to_process} 已在列表中，跳过。")
                    found_users.add(uid_to_process)
                    break
            else:
                item = QListWidgetItem(uid_to_process)
                item.setData(Qt.UserRole, {'existing_ids': existing_image_ids, 'strategy': strategy})
                self.result_list.addItem(item)
                self.append_log(f"【补全下载】已将用户 {uid_to_process} 添加到下载列表。")
                found_users.add(uid_to_process)

        if not found_users:
            self.create_info_bar("未找到任何用户配置文件进行补全下载。", is_error=False)
            self.append_log("【补全下载】未找到任何用户配置文件。")
        else:
            self.create_info_bar(f"已将 {len(found_users)} 个用户添加到补全下载队列。", is_error=False)
            if self.current_downloading_uid is None:
                self.start_next_download()

    def _read_user_json_config(self, json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.append_log(f"错误: 读取配置文件 {json_path} 失败: {e}")
            return None

    def _get_proxies(self):
        p = get_config().get('proxy', {});
        t, a, p_ = p.get('type', 'none'), p.get('address', ''), p.get('port', '')
        if t == 'none' or not a or not p_: return None
        proto = 'socks5' if t == '2' else 'http';
        return {'http': f"{proto}://{a}:{p_}", 'https': f"{proto}://{a}:{p_}"}

    def _generate_metadata_from_files(self, item_id, item_folder_path, item_type):
        self.append_log(f"【补全下载】未找到 {item_type} {item_id} 的配置文件，尝试从文件生成...")
        extracted_image_ids = set()

        path_config = get_config().get('download_path', {})
        pid_option = path_config.get('pid_option', '无')

        scan_root_dir = item_folder_path

        for root, dirs, files in os.walk(scan_root_dir):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    match = re.match(r'(\d+)', file)
                    if match:
                        extracted_image_ids.add(match.group(1))

        if not extracted_image_ids:
            self.append_log(f"【补全下载】在 {item_folder_path} 中未找到任何图片文件。")
            return None

        sorted_ids = sorted(list(extracted_image_ids), key=lambda x: int(x) if x.isdigit() else x)

        entity_name = item_id
        if item_type == 'user':
            try:
                cookie = cookie_manager.get_cookie()
                headers = {"cookie": f"PHPSESSID={cookie}", "referer": "https://www.pixiv.net",
                           "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
                proxies = self._get_proxies()
                user_profile_url = f"https://www.pixiv.net/ajax/user/{item_id}/profile/top"
                response = requests.get(user_profile_url, headers=headers, proxies=proxies, timeout=10)
                response.raise_for_status()
                user_data = response.json()
                if not user_data.get('error') and user_data.get('body', {}).get('name'):
                    entity_name = user_data['body']['name']
                else:
                    self.append_log(f"【补全下载】无法获取用户 {item_id} 的名称，将使用ID作为名称。")
            except Exception as e:
                self.append_log(f"【补全下载】获取用户 {item_id} 名称时发生错误: {e}，将使用ID作为名称。")

        meta = {
            "quantity": len(sorted_ids),
            "image_id": sorted_ids,
            "download_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "base_path": os.path.abspath(path_config.get('base_path', './downloads')),
            "uid_option": path_config.get('uid_option', 'UID'),
            "pid_option": pid_option
        }

        if item_type == 'user':
            meta["user_name"] = entity_name
            meta["user_id"] = item_id
        elif item_type == 'tag':
            meta["tag_name"] = item_id
            meta["tag_id"] = item_id

        json_file_path = os.path.join(item_folder_path, f"{item_id}.json")
        try:
            os.makedirs(os.path.dirname(json_file_path), exist_ok=True)
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self.append_log(f"【补全下载】已为 {item_type} {item_id} 生成配置文件: {json_file_path}")
            return sorted_ids
        except Exception as e:
            self.append_log(f"【补全下载】生成配置文件 {json_file_path} 失败: {e}")
            return None


if __name__ == '__main__':
    app = QApplication(sys.argv)
    from qfluentwidgets import FluentStyleSheet
    FluentStyleSheet.apply(app)

    window = User()
    window.show()
    sys.exit(app.exec_())

