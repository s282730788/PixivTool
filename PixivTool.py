# PixivTool.py

import sys
import os
from PIL import Image, ImageFilter
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QBrush, QLinearGradient, QColor, QImage
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QWidget, QSystemTrayIcon
from qfluentwidgets import (NavigationItemPosition, FluentWindow, SystemTrayMenu, Action)
from qfluentwidgets import FluentIcon as FIF, FluentStyleSheet

from app.config_manager import CONFIG_PATH, get_config
from app.download import download_manager, cookie_manager
from app.setting import Setting
from app.user import User
from app.ranking import Ranking
from app.tag import Tag

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)

DEFAULT_WIDTH, DEFAULT_HEIGHT = 900, 700
data_list = [
    {'name': 'User', 'image': "images/bg_user.jpg", 'window': User, 'icon': FIF.PEOPLE},
    {'name': 'Ranking', 'image': "images/bg_ranking.jpg", 'window': Ranking, 'icon': FIF.MARKET},
    {'name': 'Tag', 'image': "images/bg_tag.jpg", 'window': Tag, 'icon': FIF.TILES},
    {'name': 'Setting', 'image': "images/bg_setting.jpg", 'window': Setting, 'icon': FIF.SETTING}
]

class Widget(QWidget):
    def __init__(self, text: str, window=None, image=None, parent=None):
        super().__init__(parent=parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True); self.setStyleSheet("background: transparent; border: none;")
        self.background_image = self.blur_background(image)
        self.hBoxLayout = QHBoxLayout(self)
        if window: self.hBoxLayout.addWidget(window, Qt.AlignCenter)
        self.setObjectName(text.replace(' ', '-'))
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing); painter.drawPixmap(self.rect(), self.background_image)
        gradient = QLinearGradient(0, 0, 0, self.height()); gradient.setColorAt(1, QColor(231, 245, 254, 155))
        painter.setBrush(QBrush(gradient)); painter.setPen(Qt.NoPen); painter.drawRect(self.rect())
    def blur_background(self, image_path):
        try:
            image = Image.open(image_path).convert('RGB'); blurred = image.filter(ImageFilter.GaussianBlur(5))
            data = blurred.tobytes("raw", "RGB"); q_image = QImage(data, blurred.width, blurred.height, QImage.Format_RGB888)
            return QPixmap.fromImage(q_image)
        except Exception as e:
            print(f"Error loading image: {e}"); pixmap = QPixmap(800, 600); pixmap.fill(QColor("#E7F5FE")); return pixmap

# 新增 SystemTrayIcon 类
class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, parent: QWidget = None): # Parent should be the main window
        super().__init__(parent=parent)
        self.mainWindow = parent # Store reference to main window
        self.setIcon(self.mainWindow.windowIcon())
        self.setToolTip('PixivTool') # 使用更相关的提示文本

        self.menu = SystemTrayMenu(parent=self.mainWindow)
        self.show_action = Action('打开主界面', self.mainWindow)
        self.hide_action = Action('隐藏主界面', self.mainWindow)
        self.quit_action = Action('退出程序', self.mainWindow)

        self.menu.addAction(self.show_action)
        self.menu.addAction(self.hide_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)

        # 连接信号
        self.show_action.triggered.connect(self.show_main_window)
        self.hide_action.triggered.connect(self.hide_main_window)
        self.quit_action.triggered.connect(self.quit_application)
        self.activated.connect(self.on_tray_activated)

        # 初始状态更新菜单项
        self.update_menu_actions()

    def show_main_window(self):
        """显示主窗口"""
        self.mainWindow.showNormal()
        self.mainWindow.activateWindow()
        self.update_menu_actions()

    def hide_main_window(self):
        """隐藏主窗口"""
        self.mainWindow.hide()
        self.update_menu_actions()

    def quit_application(self):
        """退出应用程序"""
        self.hide() # 隐藏托盘图标
        QApplication.quit()

    def on_tray_activated(self, reason):
        """托盘图标被激活时的处理（双击）"""
        if reason == QSystemTrayIcon.DoubleClick:
            if self.mainWindow.isVisible():
                self.hide_main_window()
            else:
                self.show_main_window()

    def update_menu_actions(self):
        """根据主窗口可见性更新托盘菜单项"""
        is_visible = self.mainWindow.isVisible()
        self.show_action.setVisible(not is_visible)
        self.hide_action.setVisible(is_visible)


class Window(FluentWindow):
    def __init__(self):
        super().__init__()
        self.widget_map = {}
        self.resize_timer = QTimer(self); self.resize_timer.setSingleShot(True); self.resize_timer.timeout.connect(self.size_config)
        self.config_path = CONFIG_PATH
        self.load_config() # 加载窗口尺寸等配置
        config = get_config()
        download_manager.load_config(config)
        cookie_manager.load_cookies(config)
        download_manager.init_timer()
        self.init_widgets()
        self.initNavigation()
        self.initWindow()

        # 初始化 minimize_to_tray_enabled 标志，默认设置为 False (最小化到任务栏)
        # 这个标志的最终值将由 Setting 界面发出的信号来更新
        self.minimize_to_tray_enabled = False

        # 确保 setup_signal_bridge 在所有 widget 都初始化后调用
        self.setup_signal_bridge()

        # 初始化托盘图标
        self.systemTrayIcon = SystemTrayIcon(self)
        self.systemTrayIcon.show()

        # 设置当最后一个窗口关闭时，应用程序不退出，以便托盘图标可以继续运行
        QApplication.setQuitOnLastWindowClosed(False)

    def init_widgets(self):
        self.widget_map = {}
        for data in data_list:
            window_instance = data['window'](parent=self)
            widget = Widget(text=data['name'], window=window_instance, image=data['image'], parent=self)
            position = NavigationItemPosition.BOTTOM if data['name'] == 'Setting' else NavigationItemPosition.SCROLL
            self.widget_map[data['name']] = {'widget': widget, 'icon': data['icon'], 'name': data['name'], 'position': position}

    def setup_signal_bridge(self):
        # 确保所有实例都在连接信号之前被正确获取和定义
        setting_instance = None
        user_instance = None
        tag_instance = None
        ranking_instance = None

        try:
            setting_widget = self.widget_map.get('Setting', {}).get('widget')
            if setting_widget:
                setting_instance = setting_widget.findChild(Setting)
        except Exception as e:
            print(f"Error getting Setting widget/instance: {e}")

        try:
            user_widget = self.widget_map.get('User', {}).get('widget')
            if user_widget:
                user_instance = user_widget.findChild(User)
        except Exception as e:
            print(f"Error getting User widget/instance: {e}")

        try:
            tag_widget = self.widget_map.get('Tag', {}).get('widget')
            if tag_widget:
                tag_instance = tag_widget.findChild(Tag)
        except Exception as e:
            print(f"Error getting Tag widget/instance: {e}")

        try:
            ranking_widget = self.widget_map.get('Ranking', {}).get('widget')
            if ranking_widget:
                ranking_instance = ranking_widget.findChild(Ranking)
        except Exception as e:
            print(f"Error getting Ranking widget/instance: {e}")

        # 连接 Setting 界面发出的 minimizeMethodChanged 信号
        if setting_instance:
            setting_instance.minimizeMethodChanged.connect(self.update_minimize_method)

            # 关键：在连接建立后，立即手动触发一次更新
            # 获取 Setting 界面中 minimizeCard 的当前值
            # 这个值在 Setting.__init__ -> load_settings() 中已经被正确加载
            current_minimize_method_index = setting_instance.minimizeCard.configItem.value
            self.update_minimize_method(str(current_minimize_method_index))
        else:
            print("Warning: Setting instance not found, minimize method will not be dynamically updated.")

        # 连接其他模块的信号，并确保实例存在
        if setting_instance: # 只有当 Setting 实例存在时才尝试连接其信号
            if hasattr(setting_instance, 'threadCountChanged'):
                if user_instance and hasattr(user_instance, 'update_thread_count'):
                    setting_instance.threadCountChanged.connect(user_instance.update_thread_count)
                if tag_instance and hasattr(tag_instance, 'update_thread_count'):
                    setting_instance.threadCountChanged.connect(tag_instance.update_thread_count)
                if ranking_instance and hasattr(ranking_instance, 'update_thread_count'):
                    setting_instance.threadCountChanged.connect(ranking_instance.update_thread_count)
            if hasattr(setting_instance, 'proxyChanged'):
                if user_instance and hasattr(user_instance, 'update_proxy_info'):
                    setting_instance.proxyChanged.connect(user_instance.update_proxy_info)
                if tag_instance and hasattr(tag_instance, 'update_proxy_info'):
                    setting_instance.proxyChanged.connect(tag_instance.update_proxy_info)
                if ranking_instance and hasattr(ranking_instance, 'update_proxy_info'):
                    setting_instance.proxyChanged.connect(ranking_instance.update_proxy_info)
        else:
            print("Warning: Setting instance not found, other module signals will not be connected.")


    def load_config(self):
        width, height = DEFAULT_WIDTH, DEFAULT_HEIGHT
        if os.path.exists(self.config_path):
            try:
                config = get_config()
                if 'Window' in config:
                    width = int(config['Window'].get('width', DEFAULT_WIDTH)); height = int(config['Window'].get('height', DEFAULT_HEIGHT))
            except Exception as e: print(f"读取配置文件出错: {e}，使用默认尺寸")
        self.resize(width, height)

    def size_config(self):
        try:
            config = get_config();
            if 'Window' not in config: config['Window'] = {}
            config['Window']['width'] = str(self.width()); config['Window']['height'] = str(self.height())
            config.write()
        except Exception as e: print(f"保存窗口尺寸出错: {e}")

    def resizeEvent(self, event): self.resize_timer.start(500); super().resizeEvent(event)

    def initNavigation(self):
        for name, data in self.widget_map.items(): self.addSubInterface(data['widget'], data['icon'], data['name'], data['position'])

    def initWindow(self):
        self.setWindowIcon(QIcon('images/icon.ico')); self.setWindowTitle('PixivTool')
        desktop = QApplication.desktop().availableGeometry()
        self.move(desktop.width() // 2 - self.width() // 2, desktop.height() // 2 - self.height() // 2)
        # 再次强调，设置当最后一个窗口关闭时，应用程序不退出
        QApplication.setQuitOnLastWindowClosed(False)

    def update_minimize_method(self, method_index_str):
        """
        更新最小化行为。
        method_index_str: '0' 表示最小化到任务栏，'1' 表示最小化到托盘。
        """
        old_value = self.minimize_to_tray_enabled
        self.minimize_to_tray_enabled = (method_index_str == '1')
        # print(f"DEBUG: update_minimize_method called. Received '{method_index_str}'. minimize_to_tray_enabled changed from {old_value} to {self.minimize_to_tray_enabled}")

    def closeEvent(self, event):
        """
        重写 closeEvent，根据设置决定最小化行为。
        此方法由点击 'X' 关闭按钮触发。
        """
        # print(f"DEBUG: closeEvent triggered. minimize_to_tray_enabled is {self.minimize_to_tray_enabled}")
        if self.minimize_to_tray_enabled:
            # 如果设置为最小化到托盘，则隐藏窗口并忽略关闭事件
            event.ignore()
            self.hide()  # 直接隐藏，不先最小化到任务栏
            self.systemTrayIcon.update_menu_actions() # 更新托盘菜单状态
        else:
            # 如果设置为最小化到任务栏，或者直接点击关闭按钮，则正常退出程序
            # 隐藏托盘图标，确保程序完全退出
            self.systemTrayIcon.hide()
            event.accept()
            QApplication.quit() # 确保应用程序退出


if __name__ == '__main__':
    os.makedirs("images", exist_ok=True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling); QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    app.exec_()

