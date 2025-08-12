# config_manager.py
import os
from configobj import ConfigObj
from PyQt5.QtCore import QObject, pyqtSignal

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 配置文件路径
CONFIG_PATH = os.path.join(BASE_DIR, '../config.ini')


class ConfigManager(QObject):
    """全局配置管理器"""
    config_changed = pyqtSignal(object)  # 配置变更信号

    _instance = None

    @classmethod
    def instance(cls):
        """单例模式访问接口"""
        if cls._instance is None:
            cls._instance = ConfigManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._config = None

        # 连接到全局信号
        try:
            from app.signals import global_signals
            global_signals.response_time_interval.connect(self.update_from_signal)
        except ImportError:
            # 如果无法导入signals模块，则静默忽略
            pass

    def get_config(self):
        """获取当前配置"""
        if self._config is None:
            try:
                self._config = ConfigObj(CONFIG_PATH, encoding='utf-8')
            except Exception as e:
                print(f"加载配置文件失败: {e}")
                self._config = ConfigObj(encoding='utf-8')
                self._config.filename = CONFIG_PATH
        return self._config

    def save_config(self):
        """保存配置到文件"""
        try:
            if self._config:
                self._config.filename = CONFIG_PATH  # 确保指定文件名
                self._config.write()
                # 发出配置已更改信号
                self.config_changed.emit(self._config)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False

    def update_from_signal(self, config_data):
        """从信号接收配置更新"""
        # 将接收到的数据转换为ConfigObj格式并更新
        if isinstance(config_data, dict):
            config = self.get_config()  # 确保配置已加载
            for section, values in config_data.items():
                if section not in config:
                    config[section] = {}
                if isinstance(values, dict):
                    for key, value in values.items():
                        config[section][key] = str(value)
            # 保存更新后的配置
            self.save_config()

    def request_config_update(self):
        """请求最新配置"""
        try:
            from app.signals import global_signals
            global_signals.request_time_interval.emit()
        except ImportError:
            pass


# 创建全局单例
_config_manager = ConfigManager.instance()


# 兼容原有接口
def get_config():
    """获取配置文件对象"""
    return _config_manager.get_config()


def save_config(config):
    """保存配置文件"""
    _config_manager._config = config
    return _config_manager.save_config()


# 导出单例供直接使用
config_manager = _config_manager
