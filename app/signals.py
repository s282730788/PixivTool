from PyQt5.QtCore import QObject, pyqtSignal


class GlobalSignals(QObject):
    """
    全局信号中心，用于在不同窗口间传递消息
    所有信号都在这里定义
    """
    # 请求时间间隔值的信号（无参数）
    request_time_interval = pyqtSignal()

    # 响应时间间隔值的信号（带时间值参数）
    response_time_interval = pyqtSignal(dict)


# 创建全局信号单例
global_signals = GlobalSignals()