# setting.py
import os
import sys
import time
import weakref
import re
from PyQt5.QtCore import Qt, pyqtSignal, QStandardPaths, QTimer, QSize, QUrl, QThread
from PyQt5.QtGui import QColor, QIcon, QIntValidator
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QFileDialog, QHBoxLayout, QVBoxLayout,
                             QListWidget, QListWidgetItem, QDialog, QFrame, QProgressDialog, QLineEdit,
                             QMessageBox, QTextEdit, QScrollArea, QGraphicsDropShadowEffect)
from qfluentwidgets import (SettingCardGroup, OptionsSettingCard, ScrollArea,
                            ExpandLayout, SwitchSettingCard, ExpandGroupSettingCard,
                            OptionsConfigItem, OptionsValidator, EnumSerializer,
                            isDarkTheme, FluentIcon as FIF,
                            SettingCard, ComboBox, PrimaryPushButton, LineEdit, MessageBox,
                            PushButton)
from .name import get_user_profile

# 移除从PixivTool的导入
from app.config_manager import get_config, CONFIG_PATH
from app.signals import global_signals  # 导入全局信号

# 获取项目根目录并添加到系统路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# 修复1: 添加WebEngine环境变量设置
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

threadCountChanged = pyqtSignal(int)  # 线程数量改变信号

# 检查 WebEngine 支持
try:
    # 修复2: 提前导入WebEngine核心模块
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage
    from PyQt5.QtWebEngineCore import QWebEngineCookieStore
    from PyQt5.QtNetwork import QNetworkCookie, QNetworkProxy

    WEBENGINE_AVAILABLE = True
except ImportError as e:
    WEBENGINE_AVAILABLE = False
    print(f"警告: PyQtWebEngine 不可用，将无法使用浏览器登录功能: {e}")


# 在文件顶部添加这些函数
def setup_webengine_proxy(proxy_settings):
    """为WebEngine设置代理"""
    if not proxy_settings or proxy_settings.get('type', 0) == 0:
        # 系统代理
        print("使用系统代理设置")
        return

    proxy_type = proxy_settings['type']
    proxy_address = proxy_settings.get('address', '')
    proxy_port = proxy_settings.get('port', '')

    if not proxy_address or not proxy_port:
        print("代理地址或端口无效")
        return

    # 创建代理对象
    proxy = QNetworkProxy()

    if proxy_type == 1:  # HTTP代理
        proxy.setType(QNetworkProxy.HttpProxy)
        print(f"设置HTTP代理: {proxy_address}:{proxy_port}")
    elif proxy_type == 2:  # SOCKS5代理
        proxy.setType(QNetworkProxy.Socks5Proxy)
        print(f"设置SOCKS5代理: {proxy_address}:{proxy_port}")

    proxy.setHostName(proxy_address)
    proxy.setPort(int(proxy_port))

    # 设置应用级代理
    QNetworkProxy.setApplicationProxy(proxy)
    print("应用级代理已设置")


def cleanup_proxy_settings():
    """清理代理设置"""
    # 重置为无代理
    QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))
    # 清除环境变量
    os.environ.pop('HTTP_PROXY', None)
    os.environ.pop('HTTPS_PROXY', None)
    print("代理设置已清理")


# 新增：测试线程
class TestCookieThread(QThread):
    _signal = pyqtSignal(str, str, str)

    def __init__(self, cookie, proxy_settings):
        super().__init__()
        self.cookie = cookie
        self.proxy_settings = proxy_settings  # 代理设置字典
        print(f"Cookie: {self.cookie}, 代理设置: {self.proxy_settings}")  # 调试信息

    def run(self):
        try:
            print(f"线程启动: cookie={self.cookie[:10]}...")  # 避免打印完整cookie
            print(f"代理设置类型: {type(self.proxy_settings)}, 内容: {self.proxy_settings}")
            self.cookie_test_()
        except Exception as e:
            import traceback
            print(f"TestCookieThread 运行时错误: {e}")
            print(traceback.format_exc())
            self._signal.emit("error", "", "")
        finally:
            # 确保线程安全退出
            self.quit()
            self.wait(1000)  # 等待线程结束

    def cookie_test_(self):
        if not self.cookie:
            self._signal.emit("cookie_no", "", "")
            return

        try:
            # 调用封装的函数获取用户信息，传入代理设置字典
            status, name, profile_path = get_user_profile(self.cookie, self.proxy_settings)
            self._signal.emit(status, name, profile_path)
        except Exception as e:
            print(f"Error in cookie_test_: {e}")
            self._signal.emit("cookie_no", "", "")


class AccountManager:
    """账号管理器，负责账号的存储和加载"""

    def __init__(self, config):
        self.config_file = CONFIG_PATH
        self.config = config  # 使用主配置对象
        self.load_accounts()

    def update_account_name(self, old_name, new_name):
        """更新账号名称"""
        if old_name in self.accounts:
            # 保存旧账户的cookies
            cookies = self.accounts[old_name]
            # 删除旧账户
            del self.accounts[old_name]
            # 添加新账户名
            self.accounts[new_name] = cookies
            self.save_accounts()
            print(f"已更新账户名: {old_name} -> {new_name}")
            return True
        return False

    def add_account(self, account_name, cookies, avatar_path=''):
        phpsessid = cookies.get('PHPSESSID', '')
        if not phpsessid:
            return False

        # 保存完整信息
        self.accounts[account_name] = {
            'cookies': {'PHPSESSID': phpsessid},
            'avatar_path': avatar_path
        }
        self.save_accounts()
        return True

    def update_account(self, account_name, cookies):
        """更新账号Cookies"""
        if account_name in self.accounts:
            self.accounts[account_name] = cookies
            self.save_accounts()

    def remove_account(self, account_name):
        """删除账号"""
        if account_name in self.accounts:
            del self.accounts[account_name]
            self.save_accounts()
            print(f"已删除账号: {account_name}")

    def get_account_cookies(self, account_name):
        """获取账号Cookies"""
        return self.accounts.get(account_name, {})

    def save_accounts(self):
        # 确保Accounts节存在
        if 'Accounts' not in self.config:
            self.config['Accounts'] = {}

        # 清空旧账号
        if 'Accounts' in self.config:
            self.config['Accounts'].clear()

        # 添加新账号
        for name, info in self.accounts.items():
            self.config['Accounts'][name] = {
                'cookies': info['cookies'],
                'avatar_path': info.get('avatar_path', '')
            }

        # 保存整个配置
        self.config.write()
        print(f"账号信息已保存到 {self.config_file}")

        # 验证保存结果
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                print("配置文件内容:")
                print(f.read())
        else:
            print(f"错误：配置文件 {self.config_file} 不存在")

    def load_accounts(self):
        self.accounts = {}
        if 'Accounts' in self.config:
            for name, info in self.config['Accounts'].items():
                # 兼容旧格式
                if isinstance(info, dict):
                    self.accounts[name] = {
                        'cookies': info.get('cookies', {}),
                        'avatar_path': info.get('avatar_path', '')
                    }
                else:  # 旧版本兼容
                    self.accounts[name] = {
                        'cookies': {'PHPSESSID': info},
                        'avatar_path': ''
                    }
        # print(f"已加载 {len(self.accounts)} 个账号")

    def get_account_names(self):
        """获取所有账号名称"""
        return list(self.accounts.keys())


class PixivLoginWindow(QDialog):
    """无痕模式 Pixiv 登录窗口"""

    def __init__(self, account_name=None, proxy_settings=None, parent=None):
        super().__init__(parent)
        self.account_name = account_name
        self.proxy_settings = proxy_settings  # 保存代理设置
        self.setWindowTitle(f"Pixiv 登录 - {account_name}" if account_name else "Pixiv 登录")
        self.setGeometry(100, 100, 900, 700)
        self.setWindowIcon(QIcon(":icon.png"))

        # 存储获取的 Cookies
        self.cookies = {}
        self.cookies_ready = False
        self.profile = None
        self.web_page = None
        self.browser = None

        # 确保UI控件存在
        self.cookies_display = None

        self.setup_ui()

        if WEBENGINE_AVAILABLE:
            # 这些连接在每次重新加载时都会重新建立
            self.cookie_store.cookieAdded.connect(self.on_cookie_added)
            self.browser.urlChanged.connect(self.check_url)

            # 设置超时定时器（5分钟）
            self.timeout_timer = QTimer(self)
            self.timeout_timer.timeout.connect(self.timeout_close)
            self.timeout_timer.start(5 * 60 * 1000)  # 5分钟超时
        else:
            if hasattr(self, 'status_label'):
                self.status_label.setText("错误: PyQtWebEngine 不可用，请安装 PyQtWebEngine 模块")
            if hasattr(self, 'browser'):
                self.browser.setText("请运行命令: pip install PyQtWebEngine")

    def setup_ui(self):
        """设置极简UI布局"""
        layout = QVBoxLayout(self)

        # 设置背景样式 - 添加这行
        self.setStyleSheet("""
                    QDialog {
                        background-color: white;
                        border: 1px solid #E0E0E0;
                    }
                    QFrame {
                        background-color: #f0f0f0;
                    }
                """)

        # 状态标签
        self.status_label = QLabel("正在加载 Pixiv 登录页面...")
        self.status_label.setStyleSheet("font-weight: bold; color: #333;")
        layout.addWidget(self.status_label)

        # 浏览器视图
        if WEBENGINE_AVAILABLE:
            self.browser = QWebEngineView()
            layout.addWidget(self.browser, 1)
            self.load_pixiv_login()  # 加载登录页面
        else:
            self.browser = QLabel("浏览器组件不可用")
            layout.addWidget(self.browser)

        # 添加Cookies显示区域
        cookies_frame = QFrame()
        cookies_frame.setFrameShape(QFrame.StyledPanel)
        cookies_frame.setStyleSheet("background-color: #f0f0f0; padding: 10px;")
        cookies_layout = QVBoxLayout(cookies_frame)

        cookies_label = QLabel("当前Cookies:")
        cookies_label.setStyleSheet("font-weight: bold;")
        cookies_layout.addWidget(cookies_label)

        # 确保cookies_display被正确创建
        self.cookies_display = QTextEdit()
        self.cookies_display.setReadOnly(True)
        self.cookies_display.setMaximumHeight(60)
        self.cookies_display.setStyleSheet("background-color: white; border: 1px solid #ccc;")
        cookies_layout.addWidget(self.cookies_display)

        layout.addWidget(cookies_frame)

        # 底部按钮
        btn_layout = QHBoxLayout()

        self.cancel_btn = PushButton(self.tr('取消'), self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.retry_btn = PushButton(self.tr('重试'), self)
        self.retry_btn.clicked.connect(self.retry_login)
        btn_layout.addWidget(self.retry_btn)

        self.save_btn = PrimaryPushButton(self.tr('保存Cookies'), self)
        self.save_btn.clicked.connect(self.save_cookies)
        self.save_btn.setEnabled(False)
        btn_layout.addWidget(self.save_btn)
        btn_layout.setSpacing(0)

        layout.addLayout(btn_layout)

        # 初始化显示
        self.update_cookies_display()

    def update_cookies_display(self):
        """更新Cookies显示"""
        if not hasattr(self, 'cookies_display') or self.cookies_display is None:
            # 如果cookies_display不存在，尝试创建它
            return

        if self.cookies:
            cookies_str = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
            self.cookies_display.setText(cookies_str)
            if hasattr(self, 'save_btn'):
                self.save_btn.setEnabled(True)
        else:
            self.cookies_display.setText("尚未获取Cookies")
            if hasattr(self, 'save_btn'):
                self.save_btn.setEnabled(False)

    def load_pixiv_login(self):
        # 设置WebEngine代理
        setup_webengine_proxy(self.proxy_settings)

        """加载 Pixiv 登录页面（每次都是全新状态）"""

        # 确保清理旧的profile和页面
        if self.web_page is not None:
            try:
                self.web_page.deleteLater()
            except RuntimeError:
                pass  # 对象可能已被删除
            self.web_page = None

        if self.profile is not None:
            try:
                self.profile.deleteLater()
            except RuntimeError:
                pass
            self.profile = None

        # 创建全新的profile（无痕模式）
        self.profile = QWebEngineProfile(str(time.time()), self)  # 使用时间戳确保唯一
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)

        # 创建全新的页面
        self.web_page = QWebEnginePage(self.profile, self.browser)
        self.browser.setPage(self.web_page)

        # 设置cookie存储
        self.cookie_store = self.web_page.profile().cookieStore()
        self.cookie_store.cookieAdded.connect(self.on_cookie_added)

        # 重置状态
        self.cookies = {}
        self.cookies_ready = False
        self.update_cookies_display()

        # 加载登录页面
        login_url = QUrl(
            "https://accounts.pixiv.net/login?return_to=https%3A%2F%2Fwww.pixiv.net%2F&lang=zh&source=pc&view_type=page&force_mode=login")
        self.browser.load(login_url)
        self.status_label.setText("请登录您的 Pixiv 账号")

        # 监听URL变化
        self.browser.urlChanged.connect(self.check_url)

    def check_url(self, url):
        """检查URL变化，登录成功后自动获取Cookies"""
        url_str = url.toString()

        # 如果URL是Pixiv首页（登录成功）
        if "www.pixiv.net" in url_str and "login" not in url_str:
            self.status_label.setText("登录成功！正在获取Cookies...")
            self.status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")

            # 加载所有Cookies
            self.cookie_store.loadAllCookies()

            # 设置超时自动处理
            QTimer.singleShot(3000, self.finalize_cookies)

    def on_cookie_added(self, cookie):
        """处理添加的Cookie"""
        try:
            cookie_name = cookie.name().data().decode()
            cookie_value = cookie.value().data().decode()
        except UnicodeDecodeError:
            # 处理非UTF-8编码
            cookie_name = cookie.name().data().decode('latin1')
            cookie_value = cookie.value().data().decode('latin1')

        # 只保存PHPSESSID和关键Cookies
        if cookie_name in ["PHPSESSID", "device_token", "login_ever"]:
            self.cookies[cookie_name] = cookie_value
            self.update_cookies_display()

    def finalize_cookies(self):
        """最终处理Cookies"""
        # 检查是否获取到关键Cookie
        if "PHPSESSID" in self.cookies:
            self.cookies_ready = True
            self.status_label.setText("Cookies获取成功！")
        else:
            # 再等2秒后重试
            QTimer.singleShot(2000, self.finalize_cookies)

    def save_cookies(self):
        """保存Cookies并关闭窗口"""
        if not self.cookies:
            QMessageBox.warning(self, "无Cookies", "尚未获取任何Cookies")
            return

        # 检查PHPSESSID是否存在
        if 'PHPSESSID' not in self.cookies:
            QMessageBox.warning(self, "获取失败", "未找到PHPSESSID")
            return

        # 直接关闭窗口，不显示成功消息
        self.accept()

    def retry_login(self):
        """重试登录"""
        self.cookies = {}
        self.browser.reload()
        self.status_label.setText("正在重新加载登录页面...")
        self.status_label.setStyleSheet("font-weight: bold; color: #333;")
        self.update_cookies_display()

    def timeout_close(self):
        """超时关闭窗口"""
        if not self.cookies_ready:
            QMessageBox.warning(self, "超时", "登录过程超时，请重试")
            self.reject()


class CookiesBrowserWindow(QDialog):
    """使用Cookies登录的浏览器窗口"""

    def __init__(self, account_name, cookies, proxy_settings, parent=None):
        super().__init__(parent)
        self.proxy_settings = proxy_settings  # 保存代理设置
        self.setWindowTitle(f"Pixiv - {account_name}")
        self.setGeometry(200, 200, 1280, 800)
        self.setWindowIcon(QIcon(":icon.png"))

        # 设置背景样式 - 添加这行
        self.setStyleSheet("""
                    QDialog {
                        background-color: white;
                        border: 1px solid #E0E0E0;
                    }
                    QLabel {
                        background-color: transparent;
                    }
                """)

        # 创建布局
        layout = QVBoxLayout(self)

        # 状态标签
        self.status_label = QLabel(f"正在使用 {account_name} 的Cookies登录Pixiv...")
        self.status_label.setStyleSheet("font-weight: bold; color: #333; padding: 10px;")
        layout.addWidget(self.status_label)

        # 浏览器视图
        self.browser = QWebEngineView()
        layout.addWidget(self.browser, 1)

        # 设置Cookies并加载页面
        self.setup_browser(cookies)

    def setup_browser(self, cookies):
        # 应用代理设置（在创建任何WebEngine组件之前）
        setup_webengine_proxy(self.proxy_settings)

        """设置浏览器并加载Pixiv页面"""
        if not WEBENGINE_AVAILABLE:
            self.status_label.setText("错误: PyQtWebEngine 不可用，无法使用浏览器功能")
            return

        # 创建新的profile（确保隔离）
        profile = QWebEngineProfile(f"pixiv_{time.time()}", self)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)

        # 创建页面
        page = QWebEnginePage(profile, self.browser)
        self.browser.setPage(page)

        # 获取cookie存储
        cookie_store = page.profile().cookieStore()

        # 设置所有Cookies
        for name, value in cookies.items():
            # 创建QNetworkCookie对象
            cookie = QNetworkCookie()
            cookie.setName(name.encode('utf-8'))
            cookie.setValue(value.encode('utf-8'))
            cookie.setDomain(".pixiv.net")  # 设置域
            cookie.setPath("/")  # 设置路径

            # 添加到cookie存储
            cookie_store.setCookie(cookie, QUrl("https://www.pixiv.net"))

        # 当所有Cookies设置完成后加载页面
        QTimer.singleShot(1000, self.load_pixiv)

    def closeEvent(self, event):
        """窗口关闭时清理代理设置"""
        cleanup_proxy_settings()
        super().closeEvent(event)

    def load_pixiv(self):
        """加载Pixiv网站"""
        self.status_label.setText("正在加载Pixiv...")
        self.browser.load(QUrl("https://www.pixiv.net/"))

        # 检查登录状态
        self.browser.urlChanged.connect(self.check_login_status)

    def check_login_status(self, url):
        """检查登录状态"""
        url_str = url.toString()
        if "www.pixiv.net" in url_str and "login" not in url_str:
            self.status_label.setText("登录成功！")
            self.status_label.setStyleSheet("font-weight: bold; color: #4CAF50; padding: 10px;")


class AccountWidget(QWidget):
    """账号列表项控件，包含头像、账号名、Cookie输入框和操作按钮"""

    def __init__(self, account_name, cookies, setting, avatar_path='', parent=None):
        super().__init__(parent)
        self.account_name = account_name
        self.cookies = cookies
        self.setting = setting  # 添加Setting实例
        self.parent = parent
        self.avatar_path = avatar_path  # 新增：存储头像路径
        self.setup_ui()

        # 初始时如果有头像路径，则加载头像
        if self.avatar_path and os.path.exists(self.avatar_path):
            self.set_avatar(self.avatar_path)

    def setup_ui(self):
        # 创建阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 2)

        # 主布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.setMinimumHeight(80)
        self.setMinimumWidth(400)
        # 左侧：头像区域
        avatar_container = QWidget()
        avatar_container.setFixedWidth(60)
        avatar_container.setStyleSheet("""
            QWidget {
                border: none;
                background-color: transparent; 
            }
        """)

        avatar_layout = QVBoxLayout(avatar_container)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        avatar_layout.setSpacing(0)

        # 头像标签
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(56, 56)

        # 账号名标签
        self.name_label = QLabel(self.account_name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet("""
            QLabel {
                font-family: "Microsoft YaHei";
                font-size: 10px;
                color: #666666;
                background-color: rgba(233, 255, 0, 0.8);
            }
        """)
        self.name_label.setFixedHeight(15)

        avatar_layout.addWidget(self.avatar_label, 0, Qt.AlignCenter)
        avatar_layout.addWidget(self.name_label, 0, Qt.AlignCenter)
        layout.addWidget(avatar_container)

        # 中间：Cookie输入框
        input_container = QWidget()
        input_container.setFixedHeight(56)
        input_container.setStyleSheet("""QWidget{
                                        background-color: transparent; 
                                        border:none;
                                        border-radius: 0px;}""")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(5)

        # 添加弹簧使输入框底部对齐
        input_layout.addStretch(1)

        # Cookie输入框 - 只显示PHPSESSID部分
        self.cookie_edit = QLineEdit()
        self.cookie_edit.setPlaceholderText("粘贴Cookie或从浏览器获取")
        # print(self.cookies)
        # 只提取并显示PHPSESSID部分
        if 'PHPSESSID' in self.cookies:
            phpsessid_value = self.cookies['PHPSESSID']
            self.cookie_edit.setText(f"PHPSESSID={phpsessid_value}")

        self.cookie_edit.setStyleSheet("""
            QLineEdit {
                border: none;
                color: #555555;
                font-size: 15px;
                font-family: "Microsoft YaHei";
                padding-right: 10px;
                padding-left: 10px;
                border-bottom: 1px solid #FAB97F;
                background-color: transparent;  /* 关键修改：透明背景 */
            }
            QLineEdit:hover {
                border-bottom: 2px solid #FF8282;
                padding-top: 1px;
            }
            QLineEdit:focus {
                border-bottom: 2px solid #FF8282;
                padding-top: 1px;
            }
        """)

        # ... 样式设置保持不变 ...
        input_layout.addWidget(self.cookie_edit)

        # 右侧：操作按钮容器 - 使用垂直布局实现底部对齐
        button_container = QWidget()
        button_container.setStyleSheet("background-color: transparent; ")
        button_layout = QVBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)

        # 添加弹簧使按钮底部对齐
        button_layout.addStretch(1)

        # 按钮的水平布局
        btn_hbox = QHBoxLayout()
        btn_hbox.setContentsMargins(0, 0, 0, 0)
        btn_hbox.setSpacing(5)

        # 测试按钮
        self.test_btn = PushButton("测试", self)
        self.test_btn.setFixedSize(60, 28)
        btn_hbox.addWidget(self.test_btn)

        # 打开按钮
        self.open_btn = PushButton("打开", self)
        self.open_btn.setFixedSize(60, 28)
        btn_hbox.addWidget(self.open_btn)

        # 删除按钮
        self.delete_btn = PrimaryPushButton("删除", self)
        self.delete_btn.setFixedSize(60, 28)
        btn_hbox.addWidget(self.delete_btn)

        button_layout.addLayout(btn_hbox)

        # 添加到主布局
        layout.addWidget(avatar_container)
        layout.addWidget(input_container, 1)  # 添加伸缩因子
        layout.addWidget(button_container)

        # 设置整个布局底部对齐
        layout.setAlignment(avatar_container, Qt.AlignBottom)
        layout.setAlignment(input_container, Qt.AlignBottom)
        layout.setAlignment(button_container, Qt.AlignBottom)

    def open_with_cookies(self):
        """使用代理设置打开浏览器"""
        try:
            print(f"打开账号: {self.account_name}")

            # 获取当前代理设置
            proxy_settings = self.setting.get_proxy_settings()
            print(f"使用的代理设置: {proxy_settings}")

            # 调用Setting类的登录方法（传递代理设置）
            self.setting.login_with_cookies(self.account_name,
                                            self.cookie_edit.text().strip(),
                                            proxy_settings)
        except Exception as e:
            import traceback
            print(f"打开浏览器时出错: {e}")
            print(traceback.format_exc())
            MessageBox("错误", f"打开浏览器失败: {e}", self.setting).exec_()

    def on_cookie_changed(self):
        """当Cookie编辑框内容变更时"""
        # 更新cookies字典
        cookie_text = self.cookie_edit.text().strip()
        if cookie_text.startswith("PHPSESSID="):
            # 提取PHPSESSID值
            parts = cookie_text.split("=", 1)
            if len(parts) > 1:
                self.cookies = {'PHPSESSID': parts[1].split(";")[0].strip()}

        # 通知设置类保存配置
        self.setting.save_settings()

    def set_avatar(self, image_path):
        """设置圆形头像"""
        self.avatar_label.setStyleSheet("""QLabel{
                                                                            border-radius: 4px;
                                                                            border-image: url(%s);                                                                           
                                                                            }""" % image_path)

    def test_cookie(self):
        """测试Cookie有效性"""
        try:
            print(f"开始测试账号: {self.account_name}")

            # 获取当前Cookie
            cookie_str = self.cookie_edit.text().strip()
            try:
                cookie_sub = re.search("PHPSESSID(.*?);", cookie_str)[0].replace(";", "")
                self.cookie_edit.setText(cookie_sub)
                print(f"测试的Cookie: {cookie_str[:20]}...")  # 只打印部分Cookie

                if 'PHPSESSID' in cookie_str:
                    parts = cookie_sub.split("=", 1)
                    if len(parts) > 1:
                        self.cookies = {'PHPSESSID': parts[1].split(";")[0].strip()}
            except:
                cookie_sub = cookie_str

            # 防止重复启动测试
            if hasattr(self, 'test_thread') and self.test_thread and self.test_thread.isRunning():
                print("测试正在进行中，请勿重复点击")
                return

            # 从父组件获取代理设置
            proxy_settings = self.setting.get_proxy_settings()
            print(f"代理设置: {proxy_settings}")

            # 启动测试线程
            print("启动测试线程...")
            self.test_thread = TestCookieThread(cookie_sub, proxy_settings)
            self.test_thread._signal.connect(self.handle_test_result)
            self.test_thread.finished.connect(self.on_test_finished)
            # 禁用测试按钮
            self.test_btn.setEnabled(False)
            self.test_thread.start()
        except Exception as e:
            import traceback
            print(f"启动测试线程时出错: {e}")
            print(traceback.format_exc())
            self.test_btn.setEnabled(True)

    def on_test_finished(self):
        """测试线程完成时的处理"""
        self.test_btn.setEnabled(True)

        # 清理线程引用
        if self.test_thread:
            self.test_thread.deleteLater()
            self.test_thread = None

    def handle_test_result(self, status, name, profile):
        """处理测试结果"""
        # 重新启用测试按钮
        self.test_btn.setEnabled(True)
        if status == "ok":
            # 更新账号管理器中的信息
            self.setting.account_manager.accounts[self.account_name] = {
                'cookies': self.cookies,
                'avatar_path': profile
            }

            # 保存到配置文件
            self.setting.account_manager.save_accounts()

            # 保存旧账户名
            old_name = self.account_name

            # 更新UI显示
            if name:
                # 设置新账户名
                new_name = name
                self.name_label.setText(new_name)
                self.account_name = new_name

                # 更新账户名
                self.setting.update_account_name(old_name, new_name)

            if profile:
                # 保存头像路径
                self.avatar_path = profile
                self.set_avatar(profile)
                # 立即保存设置
                self.setting.save_settings()

            # 更新输入框样式为绿色
            self.cookie_edit.setStyleSheet("""
                QLineEdit {
                    border: none;
                    color: #555555;
                    font-size: 15px;
                    font-family: "Microsoft YaHei";
                    padding-right: 10px;
                    padding-left: 10px;
                    border-bottom: 2px solid #93f949;     
                    background-color: transparent;              
                }
                QLineEdit:hover {
                    border-bottom: 2px solid #93f949;
                    padding-top: 1px;
                }
                QLineEdit:focus {
                    border-bottom: 2px solid #93f949;
                    padding-top: 1px;
                }
            """)
        else:
            # 更新输入框样式为红色
            self.cookie_edit.setStyleSheet("""
                QLineEdit {
                    border: none;
                    color: #555555;
                    font-size: 15px;
                    font-family: "Microsoft YaHei";
                    padding-right: 10px;
                    padding-left: 10px;
                    border-bottom: 2px solid #f44336;
                    background-color: transparent;
                }
                QLineEdit:hover {
                    border-bottom: 2px solid #f44336;
                    padding-top: 1px;
                }
                QLineEdit:focus {
                    border-bottom: 2px solid #f44336;
                    padding-top: 1px;
                }
            """)


# 修复后的 ExpandGroupSettingCard 类
class FixedExpandGroupSettingCard(ExpandGroupSettingCard):
    """ 修复高度计算问题的 ExpandGroupSettingCard """

    def _adjustViewSize(self):
        """ 修复高度计算问题 """
        # 使用布局的实际推荐高度
        h = self.viewLayout.sizeHint().height()
        self.spaceWidget.setFixedHeight(h + 100)  # 加100后多出的高度消失了

        if self.isExpand:
            self.setFixedHeight(self.card.height() + h)


class Setting(ScrollArea):
    start_signal = pyqtSignal()
    folderChanged = pyqtSignal(list)
    threadCountChanged = pyqtSignal(int)  # 线程数量改变信号
    proxyChanged = pyqtSignal(str)  # 代理设置改变新号
    downloadGifChanged = pyqtSignal(bool)  # 动图下载设置改变信号
    minimizeMethodChanged = pyqtSignal(str)  # 最小化方法改变信号

    def __init__(self, parent=None):
        super().__init__(parent)
        global_signals.request_time_interval.connect(self.handle_request)

        # 从主程序导入配置路径
        self.config = get_config()
        print(f"配置文件路径: {CONFIG_PATH}")
        self.test_list = []

        self.setWindowTitle('设置')
        self.base_path = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        self.proxy_address = ""
        self.proxy_port = ""
        self.thread_count = 1  # 默认单线程
        self.download_gif = False  # 默认不下载动图
        self.minimize_method = "最小化到任务栏"  # 默认最小化方法
        self.account_manager = AccountManager(self.config)  # 传入主配置对象

        # 先初始化UI，再加载设置和连接信号
        self.initUI()
        self.load_settings()
        self.connect_signals()

    def initUI(self):
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.expandLayout.setSpacing(15)
        self.expandLayout.setContentsMargins(36, 0, 36, 0)

        # 设置标签
        self.settingLabel = QLabel(self.tr("软件设置"), self)
        self.settingLabel.setGeometry(36, 30, 200, 50)

        # ============================================================
        # 1. 代理设置
        # ============================================================
        self.proxy = SettingCardGroup(self.tr('代理设置'), self.scrollWidget)

        # 创建选项设置卡
        self.proxy_type = OptionsSettingCard(
            OptionsConfigItem(
                "QFluentWidgets", "ProxyType", 0,
                OptionsValidator([0, 1, 2]), EnumSerializer(int)
            ),
            FIF.LINK,
            self.tr('代理类型'),
            self.tr("选择您使用的代理类型"),
            texts=[
                self.tr('系统代理'), self.tr('HTTP代理'),
                self.tr('SOCKS5代理')
            ],
            parent=self.proxy,
        )
        self.proxy.addSettingCard(self.proxy_type)
        self.proxy_type.installEventFilter(self)

        # 代理服务器设置卡
        self.proxy_server_card = SettingCard(
            FIF.SEARCH,
            self.tr('代理服务器设置'),
            self.tr(""),
            self.proxy
        )
        self.proxy_server_card.hide()

        # 创建主容器，使用水平布局
        proxy_container = QWidget(self.proxy_server_card)
        proxy_layout = QHBoxLayout(proxy_container)
        proxy_layout.setContentsMargins(0, 0, 20, 0)
        proxy_layout.addStretch(9)

        # 地址部分
        address_label = QLabel(self.tr("地址:"), proxy_container)
        address_label.setFixedWidth(50)
        proxy_layout.addWidget(address_label)

        self.proxy_address_edit = LineEdit(proxy_container)
        self.proxy_address_edit.setPlaceholderText(self.tr("代理地址"))
        self.proxy_address_edit.setClearButtonEnabled(True)
        self.proxy_address_edit.setMinimumWidth(180)
        proxy_layout.addWidget(self.proxy_address_edit)

        # 端口部分
        port_label = QLabel(self.tr("端口:"), proxy_container)
        port_label.setFixedWidth(50)
        proxy_layout.addWidget(port_label)

        self.proxy_port_edit = LineEdit(proxy_container)
        self.proxy_port_edit.setPlaceholderText(self.tr("7890"))
        self.proxy_port_edit.setValidator(QIntValidator(1, 65535))
        self.proxy_port_edit.setClearButtonEnabled(True)
        self.proxy_port_edit.setFixedWidth(100)
        proxy_layout.addWidget(self.proxy_port_edit)

        self.proxy_server_card.hBoxLayout.addWidget(proxy_container)
        self.proxy.addSettingCard(self.proxy_server_card)

        # ============================================================
        # 2. 账号设置 - 包含头像、账号名、Cookie输入框和操作按钮
        # ============================================================
        # 使用修复后的 ExpandGroupSettingCard
        self.account = SettingCardGroup(self.tr('账号设置'), self.scrollWidget)

        self.accountGroup = FixedExpandGroupSettingCard(
            icon=FIF.PEOPLE,
            title=self.tr('账号管理'),
            content=self.tr('管理您的登录账号'),
            parent=self.account,
        )
        self.account.addSettingCard(self.accountGroup)
        # 创建账号管理按钮容器
        account_btn_container = QWidget()
        account_btn_container.setStyleSheet("""
            QWidget {border: 0px;}
        """)
        account_btn_layout = QHBoxLayout(account_btn_container)
        account_btn_layout.setContentsMargins(0, 0, 0, 0)
        account_btn_layout.setSpacing(10)

        # 添加账号按钮
        self.addAccountBtn = PrimaryPushButton(self.tr('添加账号'), account_btn_container)
        self.addAccountBtn.setFixedWidth(100)
        account_btn_layout.addWidget(self.addAccountBtn)

        # 刷新按钮
        self.refreshAccountBtn = PushButton(self.tr('刷新列表'), account_btn_container)
        self.refreshAccountBtn.setFixedWidth(100)
        account_btn_layout.addWidget(self.refreshAccountBtn)

        # 一键测试
        self.testAllBtn = PushButton(self.tr('一键测试'), account_btn_container)
        self.testAllBtn.setFixedWidth(100)
        account_btn_layout.addWidget(self.testAllBtn)

        # 将按钮容器添加到设置卡
        self.accountGroup.addWidget(account_btn_container)

        # 账号列表容器（包含滚动条）
        account_list_container = QWidget()
        account_list_container.setMinimumHeight(300)
        account_list_container.setStyleSheet("""
            QWidget {border: 0px;}
        """)
        account_list_layout = QVBoxLayout(account_list_container)
        account_list_layout.setContentsMargins(0, 0, 0, 0)
        account_list_layout.setSpacing(0)

        # 账号列表
        self.accountListWidget = QListWidget()
        self.accountListWidget.setStyleSheet("""
            QListWidget {
                background-color: #f9f9f9;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
            QListWidget::item {
                border-bottom: 1px solid #eee;
                height: 80px;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
            }
        """)
        self.accountListWidget.setAlternatingRowColors(True)

        # 添加滚动条
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setWidget(self.accountListWidget)
        scroll_area.setMinimumHeight(150)  # 设置最小高度
        scroll_area.setMaximumHeight(300)  # 设置最大高度
        scroll_area.setStyleSheet("""QScrollArea{
                                                        border:none;                                                                                                
                                                        }                                                            
                                                        QScrollBar::handle:vertical
                                                        {
                                                        width:6px;
                                                        background:rgba(0,0,0,30%);
                                                        border-radius:6px;   /* 滚动条两端变成椭圆*/
                                                        min-height:30;
                                                        }
                                                        QScrollBar::handle:vertical:hover
                                                        {
                                                        width:6px;
                                                        background:rgba(0,0,0,50%);   
                                                        /*鼠标放到滚动条上的时候，颜色变深*/
                                                        border-radius:6px;
                                                        min-height:30;
                                                        }
                                                        QScrollBar::add-line:vertical{  /*去掉上箭头*/
                                                        height:0px;
                                                        width:0px;
                                                        }            
                                                        QScrollBar::sub-line:vertical{  /*去掉下箭头*/
                                                        height:0px;
                                                        width:0px;
                                                        }                                                   
                                                        QScrollBar::sub-page:vertical {/* 滑块上面区域样式 */
                                                        background: #ffffff;
                                                        }
                                                        QScrollBar::add-page:vertical {  /* 滑块下面区域样式 */
                                                        background: #ffffff;
                                                        }
                                                        """)

        account_list_layout.addWidget(scroll_area)
        self.accountGroup.addGroupWidget(account_list_container)

        # ============================================================
        # 3. 下载设置
        # ============================================================
        self.downloadGroup = SettingCardGroup(self.tr('下载设置'), self.scrollWidget)

        # 下载路径设置
        # 创建容器和组合框
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 创建UID组合框
        self.uidComboBox = ComboBox(container)
        self.uidComboBox.addItems(['UID', '作者名'])
        self.uidComboBox.setFixedWidth(100)
        layout.addWidget(self.uidComboBox)

        # 创建分隔符标签
        separator = QLabel("/", container)
        separator.setFixedWidth(10)
        layout.addWidget(separator)

        # 创建PID组合框
        self.pidComboBox = ComboBox(container)
        self.pidComboBox.addItems(['无', 'PID', '标题'])
        self.pidComboBox.setFixedWidth(100)
        layout.addWidget(self.pidComboBox)

        # 创建选择文件夹按钮
        self.selectFolderBtn = PrimaryPushButton(self.tr('选择文件夹'), container)
        self.selectFolderBtn.setFixedWidth(100)
        layout.addWidget(self.selectFolderBtn)

        # 创建下载路径设置卡
        self.comboCard = SettingCard(
            FIF.FOLDER,
            self.tr('下载路径'),
            self.tr(self.getPreviewPath()),
            self.downloadGroup
        )
        self.comboCard.hBoxLayout.addWidget(container, 1, Qt.AlignRight)
        self.comboCard.hBoxLayout.addSpacing(10)
        self.downloadGroup.addSettingCard(self.comboCard)

        # 线程数量设置卡
        self.threadCountCard = OptionsSettingCard(
            OptionsConfigItem(
                "Download", "ThreadCount", 0,  # 默认选择第一个选项（单线程）
                OptionsValidator([0, 1, 2, 3]), EnumSerializer(int)
            ),
            FIF.SPEED_HIGH,  # 使用速度图标
            self.tr('线程数量'),
            self.tr('选择您的多线程数量'),
            texts=[
                self.tr('单线程'),
                self.tr('三线程'),
                self.tr('五线程'),
                self.tr('十线程')
            ],
            parent=self.downloadGroup
        )
        self.downloadGroup.addSettingCard(self.threadCountCard)

        # ============================================================
        # 4. 其它设置
        # ============================================================
        self.otherGroup = SettingCardGroup(self.tr('其它设置'), self.scrollWidget)

        # 最小化方法设置卡
        self.minimizeCard = OptionsSettingCard(
            OptionsConfigItem(
                "Window", "MinimizeMethod", 0,  # 默认选择第一个选项
                OptionsValidator([0, 1]), EnumSerializer(int)
            ),
            FIF.MINIMIZE,  # 使用最小化图标
            self.tr('退出设置'),
            self.tr('请选择点击关闭按钮后的方法'),
            texts=[
                self.tr('退出程序'),
                self.tr('最小化到托盘')
            ],
            parent=self.otherGroup
        )
        self.otherGroup.addSettingCard(self.minimizeCard)

        # ============================================================
        # 添加设置卡组到布局（按照要求的顺序）
        # ============================================================
        self.expandLayout.addWidget(self.proxy)  # 1. 代理设置
        self.expandLayout.addWidget(self.account)  # 2. 账号设置
        self.expandLayout.addWidget(self.downloadGroup)  # 3. 下载设置
        self.expandLayout.addWidget(self.otherGroup)  # 4. 其它设置

        # 设置滚动区域
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 80, 0, 20)

        # 设置样式
        self.__setQss()

        # 这些连接看起来是合理的，没有重复
        self.selectFolderBtn.clicked.connect(self.__onSelectFolderClicked)
        self.uidComboBox.currentTextChanged.connect(self.updatePathPreview)
        self.uidComboBox.currentTextChanged.connect(self.save_settings)
        self.pidComboBox.currentTextChanged.connect(self.updatePathPreview)
        self.pidComboBox.currentTextChanged.connect(self.save_settings)
        self.proxy_type.optionChanged.connect(self.updateProxySettingsVisibility)
        self.proxy_type.optionChanged.connect(self._onProxyChanged)
        self.threadCountCard.optionChanged.connect(self._onThreadCountChanged)
        self.minimizeCard.optionChanged.connect(self._onMinimizeMethodChanged)

        # 添加账号按钮 - 只连接一次
        self.addAccountBtn.clicked.connect(self.add_new_account)

        # 刷新按钮 - 只连接一次
        self.refreshAccountBtn.clicked.connect(self.load_accounts)

        self.testAllBtn.clicked.connect(self.test_all)

        # 加载账号
        self.load_accounts()

        self.resize(1000, 800)

    def handle_request(self):
        """处理来自其他窗口的请求"""
        time_value = self.get_current_settings()
        # print(f"[Setting] 收到请求，发送时间值: {time_value}ms")
        # 发送响应信号
        global_signals.response_time_interval.emit(time_value)

    def get_current_settings(self):
        """实时获取当前界面配置，以字典形式返回"""
        settings = {}

        # 1. 代理设置
        proxy_settings = {
            'type': str(self.proxy_type.configItem.value),
            'address': self.proxy_address_edit.text().strip(),
            'port': self.proxy_port_edit.text().strip()
        }
        settings['proxy'] = proxy_settings

        # 2. 下载路径设置
        download_path = {
            'base_path': self.base_path,
            'uid_option': self.uidComboBox.currentText(),
            'pid_option': self.pidComboBox.currentText()
        }
        settings['download_path'] = download_path

        # 3. 线程数量设置
        thread_mapping = {0: 1, 1: 3, 2: 5, 3: 10}
        thread_index = self.threadCountCard.configItem.value
        settings['thread_count'] = str(thread_mapping.get(thread_index, 1))

        # 4. 动图设置
        settings['download_gif'] = str(self.gifSettingCard.isChecked())

        # 6. 最小化方法设置
        settings['minimize_method'] = str(self.minimizeCard.configItem.value)

        # 7. 账号设置
        accounts = {}
        for i in range(self.accountListWidget.count()):
            item = self.accountListWidget.item(i)
            widget = self.accountListWidget.itemWidget(item)
            if widget:
                account_name = widget.account_name
                accounts[account_name] = {
                    'cookies': widget.cookies,
                    'avatar_path': widget.avatar_path
                }
        settings['Accounts'] = accounts

        # 8. 窗口大小设置（从配置文件中读取）
        if 'Window' in self.config:
            settings['Window'] = dict(self.config['Window'])

        return settings


    def test_all(self):
        """执行所有测试功能"""
        if not self.test_list:
            MessageBox("提示", "没有可测试的账号", self).exec_()
            return
        self.testAllBtn.setEnabled(False)
        # 依次执行每个测试功能
        for i, test_func in enumerate(self.test_list):
            QApplication.processEvents()  # 更新UI

            # 执行测试
            try:
                test_func()
            except Exception as e:
                print(f"测试失败: {e}")

            # 添加短暂延迟避免UI卡顿
            time.sleep(0.5)
        self.testAllBtn.setEnabled(True)


    def update_account_name(self, old_name, new_name):
        """更新账户名"""
        # 更新AccountManager
        success = self.account_manager.update_account_name(old_name, new_name)

        if success:
            # 更新UI显示
            for i in range(self.accountListWidget.count()):
                item = self.accountListWidget.item(i)
                widget = self.accountListWidget.itemWidget(item)
                if widget and widget.account_name == old_name:
                    widget.account_name = new_name
                    widget.name_label.setText(new_name)
                    break

            # 保存设置
            self.save_settings()
            return True
        return False

    def get_proxy_settings(self):
        """线程安全的获取代理设置方法，返回字典"""
        try:
            # 确保在主线程执行
            if QThread.currentThread() != self.thread():
                print("警告：尝试在非主线程获取代理设置")
                return {'type': 0, 'address': '', 'port': ''}

            # 正确获取代理类型值
            if hasattr(self.proxy_type, 'configItem') and hasattr(self.proxy_type.configItem, 'value'):
                proxy_type = self.proxy_type.configItem.value
            else:
                # 如果无法获取值，尝试从UI组件获取当前索引
                proxy_type = self.proxy_type.comboBox.currentIndex()

            # 获取代理地址和端口
            proxy_address = self.proxy_address_edit.text().strip()
            proxy_port = self.proxy_port_edit.text().strip()

            return {
                'type': proxy_type,
                'address': proxy_address,
                'port': proxy_port
            }
        except Exception as e:
            print(f"获取代理设置出错: {e}")
            return {
                'type': 0,
                'address': '',
                'port': ''
            }

    def get_all_settings(self):
        """获取所有设置项，以字典形式返回"""
        settings = {}

        # 代理设置
        settings['proxy'] = {
            'type': self.proxy_type.configItem.value,
            'address': self.proxy_address_edit.text().strip(),
            'port': self.proxy_port_edit.text().strip()
        }

        # 下载路径设置
        settings['download_path'] = {
            'base_path': self.base_path,
            'uid_option': self.uidComboBox.currentText(),
            'pid_option': self.pidComboBox.currentText()
        }

        # 线程设置
        if hasattr(self, 'threadCountCard'):
            # 映射索引到实际线程数
            thread_counts = {0: 1, 1: 3, 2: 5, 3: 10}
            index = self.threadCountCard.configItem.value
            settings['thread_count'] = thread_counts.get(index, 1)

        # 动图设置
        if hasattr(self, 'gifSettingCard'):
            settings['download_gif'] = self.gifSettingCard.isChecked()

        # 退出设置
        if hasattr(self, 'minimizeCard'):
            settings['minimize_method'] = self.minimizeCard.configItem.value
            # 映射索引到方法名称
            methods = {0: "最小化到任务栏", 1: "最小化到托盘"}
            settings['minimize_method_name'] = methods.get(settings['minimize_method'], "最小化到任务栏")

        # 账号设置
        settings['accounts'] = {}
        for i in range(self.accountListWidget.count()):
            item = self.accountListWidget.item(i)
            widget = self.accountListWidget.itemWidget(item)
            if widget:
                # 只保存PHPSESSID
                cookies = {}
                if 'PHPSESSID' in widget.cookies:
                    cookies['PHPSESSID'] = widget.cookies['PHPSESSID']
                settings['accounts'][widget.account_name] = cookies

        return settings

    def connect_signals(self):
        """连接所有设置项变更信号到保存方法"""
        # 代理类型
        if hasattr(self, 'proxy_type'):
            self.proxy_type.optionChanged.connect(self.save_settings)

        # 代理地址和端口
        if hasattr(self, 'proxy_address_edit'):
            self.proxy_address_edit.textChanged.connect(self.save_settings)
        if hasattr(self, 'proxy_port_edit'):
            self.proxy_port_edit.textChanged.connect(self.save_settings)

        # 线程数设置卡
        if hasattr(self, 'threadCountCard'):
            self.threadCountCard.optionChanged.connect(self.save_settings)

        # 动图设置开关卡
        if hasattr(self, 'gifSettingCard'):
            self.gifSettingCard.checkedChanged.connect(self.save_settings)

        # 退出设置卡
        if hasattr(self, 'minimizeCard'):
            self.minimizeCard.optionChanged.connect(self.save_settings)

    def load_settings(self):
        """从配置文件加载设置"""
        # 代理设置
        if 'proxy' in self.config:
            proxy_config = self.config['proxy']
            # 代理类型
            if 'type' in proxy_config:
                try:
                    proxy_type = int(proxy_config['type'])
                    self.proxy_type.setValue(proxy_type)

                    # 新增：根据代理类型更新设置卡可见性
                    self.updateProxySettingsVisibility(proxy_type)
                except (ValueError, TypeError):
                    pass
            # 代理地址
            if 'address' in proxy_config:
                self.proxy_address_edit.setText(proxy_config['address'])
            # 代理端口
            if 'port' in proxy_config:
                self.proxy_port_edit.setText(proxy_config['port'])

        # 线程数 - 确保是整数
        if 'thread_count' in self.config:
            try:
                thread_count = int(self.config['thread_count'])
                # 将线程数映射回选项索引
                thread_mapping = {1: 0, 3: 1, 5: 2, 10: 3}
                index = thread_mapping.get(thread_count, 0)
                if hasattr(self, 'threadCountCard'):
                    self.threadCountCard.setValue(index)
            except (ValueError, TypeError):
                pass

        # 下载路径设置
        if 'download_path' in self.config:
            path_config = self.config['download_path']
            if 'base_path' in path_config:
                self.base_path = path_config['base_path']
            if 'uid_option' in path_config:
                uid_option = path_config['uid_option']
                index = self.uidComboBox.findText(uid_option)
                if index >= 0:
                    self.uidComboBox.setCurrentIndex(index)
            if 'pid_option' in path_config:
                pid_option = path_config['pid_option']
                index = self.pidComboBox.findText(pid_option)
                if index >= 0:
                    self.pidComboBox.setCurrentIndex(index)
            self.updatePathPreview()

        # 动图设置
        if 'download_gif' in self.config:
            try:
                download_gif = self.config['download_gif'] == 'True'
                if hasattr(self, 'gifSettingCard'):
                    self.gifSettingCard.setChecked(download_gif)
            except (ValueError, TypeError):
                pass

        # 退出设置
        if 'minimize_method' in self.config:
            try:
                minimize_method = int(self.config['minimize_method'])
                if hasattr(self, 'minimizeCard'):
                    self.minimizeCard.setValue(minimize_method)
            except (ValueError, TypeError):
                pass

        # 账号设置
        if 'accounts' in self.config:
            accounts = self.config['accounts']
            for account_name, cookies in accounts.items():
                # 只保存PHPSESSID
                phpsessid = cookies.get('PHPSESSID', '')
                if phpsessid:
                    filtered_cookies = {'PHPSESSID': phpsessid}
                    self.add_account_item(account_name, filtered_cookies)

    def save_settings(self):
        """保存当前设置到配置文件"""
        # 代理设置
        if 'proxy' not in self.config:
            self.config['proxy'] = {}

        # 获取代理类型值
        try:
            proxy_type = self.proxy_type.configItem.value
        except Exception:
            proxy_type = 0

        self.config['proxy']['type'] = str(proxy_type)
        self.config['proxy']['address'] = self.proxy_address_edit.text().strip()
        self.config['proxy']['port'] = self.proxy_port_edit.text().strip()

        # 线程数 - 确保保存为整数
        if hasattr(self, 'threadCountCard'):
            # 获取当前选择的索引
            index = self.threadCountCard.configItem.value

            # 映射索引到实际线程数
            thread_counts = {0: 1, 1: 3, 2: 5, 3: 10}
            thread_count = thread_counts.get(index, 1)
            self.config['thread_count'] = str(thread_count)

        # 下载路径设置
        if 'download_path' not in self.config:
            self.config['download_path'] = {}

        self.config['download_path']['base_path'] = self.base_path
        self.config['download_path']['uid_option'] = self.uidComboBox.currentText()
        self.config['download_path']['pid_option'] = self.pidComboBox.currentText()

        # 动图设置
        if hasattr(self, 'gifSettingCard'):
            self.config['download_gif'] = str(self.gifSettingCard.isChecked())

        # 退出设置
        if hasattr(self, 'minimizeCard'):
            self.config['minimize_method'] = str(self.minimizeCard.configItem.value)

        # 写入文件
        self.config.write()  # 这个方法不会自动保存到文件

    def _onProxyChanged(self, item):
        if self.proxy_type.configItem.value == 0:
            self.proxyChanged.emit("系统代理")
        else:
            proxy_info = f"{str(self.proxy_type.texts[self.proxy_type.configItem.value])}: {self.proxy_address_edit.text().strip()}:{self.proxy_port_edit.text().strip()}"
            self.proxyChanged.emit(proxy_info)

    def _onThreadCountChanged(self, item):
        """线程数量选项改变时的处理"""
        # 将选项索引映射到实际线程数
        thread_counts = {
            0: 1,  # 单线程
            1: 3,  # 三线程
            2: 5,  # 五线程
            3: 10  # 十线程
        }

        # 获取当前选择的索引
        index = item.value if hasattr(item, 'value') else item

        # 更新线程数量并发出信号
        self.thread_count = thread_counts.get(index, 1)
        self.threadCountChanged.emit(self.thread_count)  # 发出信号

        print(f"线程数量已更改为: {self.thread_count}")

    def _onGifSettingChanged(self, is_checked):
        """动图设置开关改变时的处理"""
        self.download_gif = is_checked
        self.downloadGifChanged.emit(self.download_gif)

        # 根据状态更新文本
        status = self.tr("下载") if is_checked else self.tr("不下载")
        print(f"动图设置已更改为: {status}")

    def _onMinimizeMethodChanged(self, item):
        """最小化方法改变时的处理"""
        # 获取当前选择的索引
        index = item.value if hasattr(item, 'value') else item

        # 映射索引到方法名称 (这部分可以保留，用于内部逻辑或日志，但不再用于信号传递)
        methods = {
            0: "最小化到任务栏",
            1: "最小化到托盘"
        }

        # 更新最小化方法（这行是Setting类内部的记录，不影响信号传递）
        self.minimize_method = methods.get(index, "最小化到任务栏")
        self.minimizeMethodChanged.emit(str(index))

    def updateProxySettingsVisibility(self, option_value):
        """更新代理设置卡可见性"""
        # 处理不同的输入类型（可能是整数或OptionsConfigItem对象）
        try:
            index = option_value.value if hasattr(option_value, 'value') else int(option_value)
        except (ValueError, TypeError):
            index = 0

        # 根据代理类型更新UI
        if index == 0:
            self.proxy_server_card.hide()
        else:
            if index == 1:
                self.proxy_server_card.titleLabel.setText(self.tr('HTTP代理设置'))
                self.proxy_address_edit.setPlaceholderText(self.tr("HTTP代理地址"))
                self.proxy_port_edit.setPlaceholderText(self.tr("7890"))


            else:
                self.proxy_server_card.titleLabel.setText(self.tr('SOCKS5代理设置'))
                self.proxy_address_edit.setPlaceholderText(self.tr("SOCKS5代理地址"))
                self.proxy_port_edit.setPlaceholderText(self.tr("7890"))
            self.proxy_server_card.show()

        # 强制UI更新以确保布局正确
        QTimer.singleShot(0, self.forceLayoutUpdate)

    def forceLayoutUpdate(self):
        self.proxy.layout().invalidate()
        self.proxy.layout().activate()
        self.expandLayout.invalidate()
        self.expandLayout.activate()
        self.proxy.adjustSize()
        self.scrollWidget.adjustSize()
        self.scrollWidget.updateGeometry()
        self.updateGeometry()
        QApplication.processEvents()

    def getPreviewPath(self):
        # 添加检查以确保控件存在
        if not hasattr(self, 'uidComboBox') or not hasattr(self, 'pidComboBox'):
            return self.base_path

        uid = self.uidComboBox.currentText()
        pid = self.pidComboBox.currentText()
        return f"{self.base_path}/{uid}" if pid == '无' else f"{self.base_path}/{uid}/{pid}"

    def updatePathPreview(self):
        self.comboCard.contentLabel.setText(self.getPreviewPath())

    def __onSelectFolderClicked(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("选择下载文件夹"), self.base_path)
        if folder:
            self.base_path = f'{folder}/PixivDown'
            self.updatePathPreview()
            self.save_settings()  # 添加保存设置

    def load_accounts(self):
        self.accountListWidget.clear()

        # 直接使用AccountManager中的完整账号信息
        for account_name, account_info in self.account_manager.accounts.items():
            self.add_account_item(account_name, account_info)

    def add_account_item(self, account_name, account_info):
        """添加账号项到列表"""
        item = QListWidgetItem(self.accountListWidget)
        item.setSizeHint(QSize(0, 80))

        # 传递完整账号信息
        widget = AccountWidget(
            account_name,
            account_info['cookies'],
            self,
            account_info.get('avatar_path', '')
        )

        # 使用弱引用创建槽函数
        weak_self = weakref.ref(self)
        weak_widget = weakref.ref(widget)

        # 删除按钮连接
        widget.delete_btn.clicked.connect(
            lambda checked, name=account_name, ws=weak_self:
            ws().delete_account(name) if ws() else None
        )

        # 测试按钮连接
        widget.test_btn.clicked.connect(
            lambda checked, w=weak_widget:
            w().test_cookie() if w() else None
        )

        # 打开按钮连接 - 修复语法错误
        widget.open_btn.clicked.connect(
            lambda: self.open_account_handler(account_name, weak_self, weak_widget)
        )
        # 将测试功能添加到列表
        self.test_list.append(widget.test_cookie)

        self.accountListWidget.addItem(item)
        self.accountListWidget.setItemWidget(item, widget)

    def open_account_handler(self, account_name, weak_self, weak_widget):
        """处理打开账号的辅助函数"""
        if weak_self() and weak_widget():
            cookie_str = weak_widget().cookie_edit.text().strip()
            proxy_settings = weak_self().get_proxy_settings()
            weak_self().login_with_cookies(account_name, cookie_str, proxy_settings)

    def add_new_account(self):
        """添加新账号（通过无痕登录）"""
        # 自动生成账号名（使用时间戳）
        account_name = f"账号_{int(time.time())}"

        # 获取当前代理设置
        proxy_settings = self.get_proxy_settings()
        print(f"添加账号使用的代理设置: {proxy_settings}")

        # 打开无痕登录窗口（传递代理设置）
        self.login_window = PixivLoginWindow(account_name, proxy_settings, self)
        result = self.login_window.exec_()

        # 如果登录成功，获取cookies并保存
        if result == QDialog.Accepted:
            cookies = self.login_window.cookies

            # 使用AccountManager添加账号
            success = self.account_manager.add_account(
                account_name,
                self.login_window.cookies,
                avatar_path=''  # 初始为空
            )

            if success:
                self.load_accounts()
                # 保存整个设置（包含账号）
                self.save_settings()
                MessageBox("添加成功", f"已添加账号: {account_name}", self).exec_()
            else:
                MessageBox("添加失败", "未能获取有效的PHPSESSID", self).exec_()

    def login_with_cookies(self, account_name, cookie_str, proxy_settings):
        """使用Cookies登录Pixiv网站，使用指定的代理设置"""
        if not WEBENGINE_AVAILABLE:
            QMessageBox.warning(self, "功能不可用", "PyQtWebEngine 不可用，无法使用浏览器功能")
            return

        # 解析Cookie字符串
        cookies = {}
        if 'PHPSESSID' in cookie_str:
            parts = cookie_str.split("=", 1)
            if len(parts) > 1:
                cookies = {'PHPSESSID': parts[1].split(";")[0].strip()}

        if not cookies.get("PHPSESSID"):
            QMessageBox.warning(self, "无有效Cookies", "该账号没有保存有效的Cookies，请重新登录")
            return

        # 强制UI更新
        QApplication.processEvents()

        # 创建浏览器窗口，传递代理设置
        self.browser_window = CookiesBrowserWindow(account_name, cookies, proxy_settings, self)
        self.browser_window.exec_()


    def delete_account(self, account_name):
        """删除账号"""
        # 查找并移除对应的测试功能
        for i in range(self.accountListWidget.count()):
            item = self.accountListWidget.item(i)
            widget = self.accountListWidget.itemWidget(item)
            if widget and widget.account_name == account_name:
                # 从test_list中移除对应的测试功能
                if widget.test_cookie in self.test_list:
                    self.test_list.remove(widget.test_cookie)
                break
        reply = MessageBox("确认删除",
                           f"确定要删除账号 '{account_name}' 吗？",
                           self)
        reply.yesButton.setText("确定")
        reply.cancelButton.setText("取消")

        if reply.exec_():
            self.account_manager.remove_account(account_name)
            self.load_accounts()
            MessageBox("删除成功", f"已删除账号: {account_name}", self).exec_()

        self.save_settings()  # 删除后保存

    def __setQss(self):
        self.scrollWidget.setObjectName('scrollWidget')
        self.settingLabel.setObjectName('settingLabel')
        theme = 'dark' if isDarkTheme() else 'light'

        style_sheet = f"""
        #scrollWidget {{
            background: transparent;
        }}
        #settingLabel {{
            font: 30px 'Segoe UI', 'Microsoft YaHei';
            color: {'white' if theme == 'dark' else 'black'};
            padding-left: 0;
        }}
        SettingCardGroup {{
            font: 16px 'Segoe UI', 'Microsoft YaHei';
            margin-bottom: 20px;
        }}

        QLabel {{
            font: 14px 'Segoe UI', 'Microsoft YaHei';
            color: {'#cccccc' if theme == 'dark' else '#606060'};
        }}
        LineEdit {{
            min-height: 30px;
            background-color: {'#333333' if theme == 'dark' else '#ffffff'};
            border: 1px solid {'#555555' if theme == 'dark' else '#cccccc'};
            border-radius: 4px;
            padding: 5px;
        }}
        """
        self.setStyleSheet(style_sheet)
