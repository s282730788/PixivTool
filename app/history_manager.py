# app/history_manager.py

import json
import os
import datetime
import re

HISTORY_FILE = "history.json"  # 统一的历史记录文件
MAX_HISTORY_ITEMS = 20         # 最大历史记录条数

class HistoryManager:
    def __init__(self):
        self._history_data = self._load_history()

    def _load_history(self):
        """
        从文件中加载历史记录。
        尝试兼容旧的字符串格式历史记录，并将其转换为新的字典格式。
        """
        loaded_data = []
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                    for item in raw_data:
                        if isinstance(item, dict) and 'type' in item and 'id' in item and 'timestamp' in item:
                            # 新格式：已经是包含所需键的字典
                            loaded_data.append(item)
                        elif isinstance(item, str):
                            # 旧的字符串格式：例如 "[2023-10-26 10:30:00] UID_OR_TAG_NAME"
                            match = re.match(r'\[(.*?)\]\s*(.*)', item)
                            if match:
                                timestamp_str = match.group(1)
                                item_id_or_tag = match.group(2).strip()

                                # 尝试推断类型：如果全是数字，假定为 'user'，否则为 'tag'
                                item_type = 'user' if item_id_or_tag.isdigit() else 'tag'

                                loaded_data.append({
                                    "timestamp": timestamp_str,
                                    "type": item_type,
                                    "id": item_id_or_tag
                                })
                            else:
                                print(f"Warning: Could not parse old history string format: '{item}'. Skipping.")
                        else:
                            print(f"Warning: Skipping unknown history item format: '{item}'.")
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {HISTORY_FILE}: {e}. Starting with empty history.")
            # 如果 JSON 文件损坏，则从空历史记录开始
            loaded_data = []
        except Exception as e:
            print(f"Error loading history file {HISTORY_FILE}: {e}. Starting with empty history.")
            loaded_data = []

        # 确保历史记录按时间戳排序（最新在前）并截断到最大数量
        # 由于时间戳是字符串，按字符串排序通常也能达到预期效果
        loaded_data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return loaded_data[:MAX_HISTORY_ITEMS]

    def _save_history(self):
        """将历史记录保存到文件。"""
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._history_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving history file {HISTORY_FILE}: {e}")

    def add_record(self, item_type, item_id):
        """
        添加新的历史记录。
        如果同类型同ID的记录已存在，则先删除旧记录，再添加新记录到最前面。
        """
        # 移除任何现有同类型同ID的记录，确保只处理字典类型
        self._history_data = [
            r for r in self._history_data
            if not (isinstance(r, dict) and r.get('type') == item_type and r.get('id') == item_id)
        ]

        # 添加新记录到列表最前面
        record = {
            "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "type": item_type,
            "id": item_id
        }
        self._history_data.insert(0, record)
        # 保持历史记录数量在最大限制内
        self._history_data = self._history_data[:MAX_HISTORY_ITEMS]
        self._save_history()

    def get_history_records(self, filter_type=None):
        """
        获取历史记录列表。
        可选参数 filter_type 可以过滤只显示特定类型的记录 ('user' 或 'tag')。
        返回的是原始的字典列表。
        """
        if filter_type:
            # 确保 'r' 是字典类型，再尝试获取 'type'
            return [r for r in self._history_data if isinstance(r, dict) and r.get('type') == filter_type]
        # 返回所有有效的字典记录
        return [r for r in self._history_data if isinstance(r, dict)]

    def delete_record(self, item_type, item_id):
        """
        删除指定类型和ID的历史记录。
        """
        initial_len = len(self._history_data)
        # 确保 'r' 是字典类型，再尝试获取 'type' 和 'id'
        self._history_data = [
            r for r in self._history_data
            if not (isinstance(r, dict) and r.get('type') == item_type and r.get('id') == item_id)
        ]
        if len(self._history_data) < initial_len:
            self._save_history()
            return True
        return False

    def clear_all_history(self):
        """清空所有历史记录。"""
        self._history_data = []
        self._save_history()

# 创建一个共享的 HistoryManager 实例
history_manager = HistoryManager()

