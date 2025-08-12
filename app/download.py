# app/download.py

import os
import requests
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer
import re
from urllib.parse import quote

from .config_manager import get_config, ConfigManager


class CookieManager:
    _instance, _lock = None, threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None: cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'): return
        self._cookies_state, self._current_index, self._lock, self._initialized = [], 0, threading.Lock(), True

    def load_cookies(self, config):
        with self._lock:
            self._cookies_state = []
            for acc in config.get('Accounts', {}).values():
                if cookie := acc.get('cookies', {}).get('PHPSESSID'): self._cookies_state.append(
                    {'cookie': cookie, 'banned_until': 0})

    def get_cookie(self):
        with self._lock:
            if not self._cookies_state: return ""
            # 尝试找到一个未被禁用或禁用时间已过的cookie
            for _ in range(len(self._cookies_state)):
                self._current_index = (self._current_index + 1) % len(self._cookies_state)
                info = self._cookies_state[self._current_index]
                if time.time() > info['banned_until']:
                    return info['cookie']
            # 如果所有cookie都被禁用，则返回当前索引的cookie，让调用者处理等待
            if self._cookies_state:
                return self._cookies_state[self._current_index]['cookie']
            return ""

    def ban_cookie(self, cookie_to_ban):
        with self._lock:
            for info in self._cookies_state:
                if info['cookie'] == cookie_to_ban:
                    ban_time = time.time() + 180  # 禁用3分钟
                    info['banned_until'] = ban_time
                    print(f"Cookie ...{cookie_to_ban[-6:]} banned until {time.ctime(ban_time)}");
                    break

    def get_cookie_count(self):
        with self._lock:
            return len(self._cookies_state)


cookie_manager = CookieManager()


class DownloadThread(QThread):
    # 修改信号签名，增加 catalog 参数
    progress_signal = pyqtSignal(str, int, int, str, str)  # item_id, completed, total, status, catalog
    finished_signal = pyqtSignal(str, str)  # item_id, catalog
    chunk_downloaded = pyqtSignal(int)

    def __init__(self, item_id, config, catalog, item_type='user', age_mode='all', existing_image_ids=None,
                 completion_strategy='default', custom_path=None, ranking_type_name=None, ranking_date_str=None,
                 parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.config = config
        self.catalog = catalog  # 保存 catalog
        self.item_type = item_type
        self.age_mode = age_mode

        self.stop_event, self.pause_event = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.completed_works = 0
        self.total_works = 0
        self.downloaded_work_ids = []
        self.entity_name = "Unknown"

        self.existing_image_ids = set(existing_image_ids) if existing_image_ids else set()
        self.completion_strategy = completion_strategy
        self.original_existing_image_ids = set(existing_image_ids) if existing_image_ids else set()

        self.custom_download_path = custom_path
        self.ranking_type_name = ranking_type_name
        self.ranking_date_str = ranking_date_str
        self.metadata_folder = None

    def run(self):
        try:
            thread_count = int(self.config.get('thread_count', 5))
            adapter = requests.adapters.HTTPAdapter(pool_connections=thread_count, pool_maxsize=thread_count)
            self.session.mount('https', adapter)

            time.sleep(1)

            works_to_download = []
            if self.catalog == 'User':
                all_works_from_api = self._fetch_user_works(self.item_id)
                works_to_download = self._apply_completion_strategy(all_works_from_api)
            elif self.catalog == 'Tag':
                all_works_from_api = self._fetch_tag_works(self.item_id, self.age_mode)
                works_to_download = self._apply_completion_strategy(all_works_from_api)
            elif self.catalog == 'Ranking':
                works_to_download = [self.item_id]  # For Ranking, item_id is already the illust_id

            self.total_works = len(works_to_download)

            if self.stop_event.is_set(): return
            if self.total_works == 0:
                if self.catalog == 'Ranking':
                    self.progress_signal.emit(self.item_id, 0, 0, f"作品 {self.item_id} 无需下载或获取详情失败。",
                                              self.catalog)
                else:
                    self.progress_signal.emit(self.item_id, 0, 0, "没有作品需要下载或访问失败。", self.catalog)
                self._save_metadata_file()
                return

            # self.progress_signal.emit(self.item_id, 0, self.total_works,
            #                           f"找到 {self.total_works} 个作品，使用 {thread_count} 线程下载...", self.catalog)

            with ThreadPoolExecutor(max_workers=thread_count) as executor:
                future_to_work = {executor.submit(self._process_single_work, work_id): work_id for work_id in
                                  works_to_download}
                for future in as_completed(future_to_work):
                    if self.stop_event.is_set(): break
                    try:
                        success, work_id = future.result()
                        with self.lock:
                            self.completed_works += 1
                        if success:
                            self.downloaded_work_ids.append(work_id)
                            self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                                      f"作品 {work_id} 下载成功 ({self.completed_works}/{self.total_works})",
                                                      self.catalog)
                        else:
                            self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                                      f"作品 {work_id} 下载失败 ({self.completed_works}/{self.total_works})",
                                                      self.catalog)
                    except Exception as e:
                        work_id = future_to_work.get(future, "未知")
                        self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                                  f"作品 {work_id} 处理时发生错误: {e} ({self.completed_works}/{self.total_works})",
                                                  self.catalog)

        except Exception as e:
            self.progress_signal.emit(self.item_id, 0, 0, f"严重错误: {e}", self.catalog)
        finally:
            if self.catalog != 'Ranking':
                self._save_metadata_file()
            self.finished_signal.emit(self.item_id, self.catalog)  # 传递 catalog

    def _process_single_work(self, work_id):
        if self.stop_event.is_set():
            return False, work_id
        self.check_pause()

        work_details = self._get_work_details(work_id)
        if not work_details:
            self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                      f"作品 {work_id}: 详情获取失败，跳过。", self.catalog)
            return False, work_id

        if self.catalog == 'User' and self.entity_name == "Unknown":
            self.entity_name = work_details.get('user_name', 'Unknown_Author')

        work_dir = self._create_work_directory(work_details)
        if not work_dir:
            self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                      f"作品 {work_id}: 目录创建失败，跳过。", self.catalog)
            return False, work_id

        all_images_downloaded = True
        for i, image_url in enumerate(work_details['image_urls']):
            if self.stop_event.is_set():
                return False, work_id
            self.check_pause()

            if not self._download_image(image_url, work_id, work_dir):
                all_images_downloaded = False
                break

        return all_images_downloaded, work_id

    def _get_response_with_retries(self, url, headers, proxies, stream=False, timeout=20, max_retries=5):
        """
        辅助方法：封装带重试、Cookie管理和429/403处理的requests.get请求。
        headers 参数必须是可变的字典，因为会更新其中的 'cookie' 字段。
        """
        retries = 0
        while retries < max_retries:
            if self.stop_event.is_set(): return None
            self.check_pause()

            current_cookie_value = headers.get('cookie', '').split('PHPSESSID=')[-1] if 'PHPSESSID=' in headers.get(
                'cookie', '') else ""

            try:
                response = self.session.get(url, headers=headers, proxies=proxies, stream=stream, timeout=timeout)

                if response.status_code == 403:
                    if current_cookie_value:
                        cookie_manager.ban_cookie(current_cookie_value)
                    self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                              f"请求 {url}: 403错误，Cookie被禁用，尝试更换Cookie。", self.catalog)
                    # 获取新Cookie并更新headers
                    new_cookie = cookie_manager.get_cookie()
                    headers['cookie'] = f"PHPSESSID={new_cookie}"
                    time.sleep(1)  # 短暂等待后重试
                    continue  # 立即重试

                if response.status_code == 429:
                    if current_cookie_value:
                        cookie_manager.ban_cookie(current_cookie_value)  # 禁用当前Cookie 3分钟

                    num_available_cookies = cookie_manager.get_cookie_count()

                    if num_available_cookies == 1:
                        self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                                  f"请求 {url}: 429错误，只有一个Cookie，等待3分钟。", self.catalog)
                        time.sleep(180)  # 等待3分钟
                    else:
                        self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                                  f"请求 {url}: 429错误，更换Cookie并等待30秒。", self.catalog)
                        time.sleep(30)  # 等待30秒

                    # 获取新Cookie并更新headers
                    new_cookie = cookie_manager.get_cookie()
                    headers['cookie'] = f"PHPSESSID={new_cookie}"
                    continue  # 立即重试

                response.raise_for_status()  # 对于4xx或5xx的HTTP状态码抛出异常
                return response  # 成功，返回响应

            except requests.exceptions.RequestException as e:
                retries += 1
                self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                          f"请求 {url}: 网络错误或超时: {e} (重试 {retries}/{max_retries})",
                                          self.catalog)
                time.sleep(2 * retries)  # 指数退避，等待时间随重试次数增加
            except Exception as e:
                retries += 1
                self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                          f"请求 {url}: 未知错误: {e} (重试 {retries}/{max_retries})", self.catalog)
                time.sleep(2 * retries)

        self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                  f"请求 {url}: 达到最大重试次数，放弃。", self.catalog)
        return None  # 达到最大重试次数后失败

    def _fetch_user_works(self, user_id):
        cookie = cookie_manager.get_cookie()
        headers, proxies = self._get_headers(cookie), self._get_proxies()
        url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all"

        response = self._get_response_with_retries(url, headers, proxies, timeout=20)
        if not response:
            return []

        try:
            data = response.json()
            if data.get('error'): raise Exception(data.get('message', "API返回错误"))
            body = data.get('body', {});
            illusts, manga = body.get('illusts', {}), body.get('manga', {})
            return list(illusts.keys() if isinstance(illusts, dict) else []) + \
                list(manga.keys() if isinstance(manga, dict) else [])
        except Exception as e:
            self.progress_signal.emit(self.item_id, 0, 0, f"解析用户作品列表失败: {e}", self.catalog)
            return []

    def _fetch_tag_works(self, tag, age_mode):
        cookie = cookie_manager.get_cookie()
        headers, proxies = self._get_headers(cookie), self._get_proxies()
        all_tag_works = []

        initial_url = f"https://www.pixiv.net/ajax/search/artworks/{quote(tag)}?word={quote(tag)}&order=date_d&mode={age_mode}&s_mode=s_tag&p=1"
        response = self._get_response_with_retries(initial_url, headers, proxies, timeout=20)
        if not response:
            return []

        try:
            data = response.json()
            if data.get('error'): raise Exception(data.get('message', "API返回错误"))

            total_count = data.get('body', {}).get('illustManga', {}).get('total', 0)
            if total_count == 0:
                self.progress_signal.emit(self.item_id, 0, 0, f"【{tag}】关键词没有找到作品。", self.catalog)
                return []

            self.progress_signal.emit(self.item_id, 0, 0, f"【{tag}】关键词总共有【{total_count}】个作品。", self.catalog)

            pages_to_fetch = (total_count + 59) // 60

            for page in range(1, pages_to_fetch + 1):
                if self.stop_event.is_set(): break
                page_url = f"https://www.pixiv.net/ajax/search/artworks/{quote(tag)}?word={quote(tag)}&order=date_d&mode={age_mode}&s_mode=s_tag&p={page}"

                page_response = self._get_response_with_retries(page_url, headers, proxies, timeout=20)
                if not page_response:
                    self.progress_signal.emit(self.item_id, 0, 0, f"获取【{tag}】第{page}页作品失败，跳过该页。",
                                              self.catalog)
                    continue  # 跳过当前页，尝试下一页

                page_data = page_response.json()
                if page_data.get('error'):
                    self.progress_signal.emit(self.item_id, 0, 0,
                                              f"获取【{tag}】第{page}页作品API返回错误: {page_data.get('message', '')}",
                                              self.catalog)
                    continue

                page_illusts = page_data.get('body', {}).get('illustManga', {}).get('data', [])
                for illust in page_illusts:
                    all_tag_works.append(illust['id'])

            return all_tag_works
        except Exception as e:
            self.progress_signal.emit(self.item_id, 0, 0, f"获取标签作品列表失败: {e}", self.catalog)
            return []

    def _apply_completion_strategy(self, all_works_from_api):
        filtered_works = []
        if self.existing_image_ids and (self.completion_strategy == 'default' or self.completion_strategy == 'smart'):
            if self.completion_strategy == 'default':
                for work_id in all_works_from_api:
                    if work_id not in self.existing_image_ids:
                        filtered_works.append(work_id)
                self.progress_signal.emit(self.item_id, 0, 0,
                                          f"【补全下载】默认去重模式，发现 {len(all_works_from_api)} 个作品，其中 {len(filtered_works)} 个是新作品。",
                                          self.catalog)
            elif self.completion_strategy == 'smart':
                if self.existing_image_ids:
                    numeric_existing_ids = [int(x) for x in self.existing_image_ids if x.isdigit()]
                    if numeric_existing_ids:
                        max_existing_id = max(numeric_existing_ids)
                        for work_id in all_works_from_api:
                            if work_id.isdigit() and int(work_id) > max_existing_id:
                                filtered_works.append(work_id)
                        self.progress_signal.emit(self.item_id, 0, 0,
                                                  f"【补全下载】智能补全模式，最大已下载ID: {max_existing_id}，发现 {len(filtered_works)} 个新作品。",
                                                  self.catalog)
                    else:
                        filtered_works = all_works_from_api
                        self.progress_signal.emit(self.item_id, 0, 0,
                                                  f"【补全下载】智能补全模式，但无有效数字ID，将下载所有作品。",
                                                  self.catalog)
                else:
                    filtered_works = all_works_from_api
                    self.progress_signal.emit(self.item_id, 0, 0,
                                              f"【补全下载】智能补全模式，无历史记录，将下载所有作品。", self.catalog)
        else:
            filtered_works = all_works_from_api
            self.progress_signal.emit(self.item_id, 0, 0,
                                      f"【常规下载】发现 {len(all_works_from_api)} 个作品。", self.catalog)
        return filtered_works

    def _get_work_details(self, work_id):
        cookie = cookie_manager.get_cookie()
        headers, proxies = self._get_headers(cookie), self._get_proxies()
        pages_url = f"https://www.pixiv.net/ajax/illust/{work_id}/pages"
        details_url = f"https://www.pixiv.net/ajax/illust/{work_id}"

        # 注意：这里需要确保headers是可变的，以便_get_response_with_retries可以更新cookie
        # 传递headers的副本，或者确保headers对象在函数调用之间是共享的
        # 这里我们直接传递headers，因为它是局部变量，每次调用都会重新创建
        pages_res = self._get_response_with_retries(pages_url, headers, proxies, timeout=20)
        details_res = self._get_response_with_retries(details_url, headers, proxies, timeout=20)

        if not pages_res or not details_res:
            self.progress_signal.emit(self.item_id, 0, 0, f"作品 {work_id} 详情获取失败。", self.catalog)
            return None

        try:
            pages_data, details_res_data = pages_res.json(), details_res.json()
            if pages_data.get('error') or details_res_data.get('error'):
                self.progress_signal.emit(self.item_id, 0, 0,
                                          f"作品 {work_id} API返回错误: {pages_data.get('message', '')} {details_res_data.get('message', '')}",
                                          self.catalog)
                return None
            work_data = details_res_data['body']
            work_data['work_id'] = work_id
            image_urls = [p['urls']['original'] for p in pages_data['body']]
            return {'image_urls': image_urls, 'title': work_data.get('illustTitle', ''),
                    'comment': work_data.get('illustComment', ''),
                    'tags': [t['tag'] for t in work_data.get('tags', {}).get('tags', [])],
                    'create_date': work_data.get('createDate', ''), 'user_name': work_data.get('userName', ''),
                    'work_id': work_id}
        except json.JSONDecodeError:
            self.progress_signal.emit(self.item_id, 0, 0, f"作品 {work_id} 详情JSON解析失败。", self.catalog)
            return None
        except Exception as e:
            self.progress_signal.emit(self.item_id, 0, 0, f"作品 {work_id} 详情处理未知错误: {e}", self.catalog)
            return None

    def _download_image(self, image_url, work_id, work_dir):
        save_path = os.path.join(work_dir, image_url.split('/')[-1])
        temp_save_path = save_path + ".tmp"  # 临时文件路径

        # 如果最终文件已存在，则跳过下载
        if os.path.exists(save_path):
            return True

        cookie = cookie_manager.get_cookie()
        headers, proxies = self._get_headers(cookie), self._get_proxies()
        headers['Referer'] = f"https://www.pixiv.net/artworks/{work_id}"

        response = self._get_response_with_retries(image_url, headers, proxies, stream=True, timeout=30)
        if not response:
            # _get_response_with_retries 已经处理了重试和错误消息
            return False

        try:
            expected_size = int(response.headers.get('Content-Length', 0))  # 获取预期文件大小
            actual_size = 0  # 实际下载大小

            with open(temp_save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.stop_event.is_set():
                        # 如果停止事件被触发，清理临时文件并退出
                        if os.path.exists(temp_save_path):
                            os.remove(temp_save_path)
                        return False
                    self.check_pause()  # 检查是否需要暂停
                    f.write(chunk)
                    actual_size += len(chunk)  # 累加实际下载大小
                    self.chunk_downloaded.emit(len(chunk))

            # 下载到临时文件成功后，进行大小校验
            if expected_size > 0 and actual_size == expected_size:
                # 大小匹配，原子性重命名临时文件到最终路径
                os.rename(temp_save_path, save_path)
                return True
            elif expected_size == 0 and actual_size > 0:
                # 如果Content-Length未提供，但文件已下载且非空，则认为成功
                os.rename(temp_save_path, save_path)
                return True
            else:
                # 大小不匹配或文件为空，删除临时文件
                if os.path.exists(temp_save_path):
                    os.remove(temp_save_path)
                self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                          f"作品 {work_id}: 图片 {os.path.basename(save_path)} 下载大小不匹配 (预期: {expected_size}, 实际: {actual_size})。",
                                          self.catalog)
                return False  # 标记为失败，让上层逻辑决定是否重试整个作品

        except Exception as e:
            # 其他未知错误，清理临时文件
            if os.path.exists(temp_save_path):
                os.remove(temp_save_path)
            self.progress_signal.emit(self.item_id, self.completed_works, self.total_works,
                                      f"作品 {work_id}: 图片下载处理错误: {e}", self.catalog)
            return False

    def _get_headers(self, cookie):
        return {"cookie": f"PHPSESSID={cookie}", "referer": "https://www.pixiv.net",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

    def _get_proxies(self):
        p = self.config.get('proxy', {});
        t, a, p_ = p.get('type', 'none'), p.get('address', ''), p.get('port', '')
        if t == 'none' or not a or not p_: return None
        proto = 'socks5' if t == '2' else 'http';
        return {'http': f"{proto}://{a}:{p_}", 'https': f"{proto}://{a}:{p_}"}

    def _sanitize_filename(self, name):
        sanitized_name = re.sub(r'[<>:"/\\|?*]', '_', name)
        sanitized_name = sanitized_name.rstrip('.')
        sanitized_name = ''.join(c for c in sanitized_name if c.isprintable())
        return sanitized_name.strip()

    def _create_work_directory(self, work_details):
        path_config = self.config.get('download_path', {})
        base_download_root = path_config.get('base_path', './downloads')

        uid_option = path_config.get('uid_option', 'UID')
        pid_option = path_config.get('pid_option', '无')

        current_path = ""
        if self.catalog == 'User':
            first_level_folder = ""
            if uid_option == 'UID':
                first_level_folder = self._sanitize_filename(self.item_id)
            else:
                first_level_folder = self._sanitize_filename(work_details.get('user_name', 'Unknown_Author'))
            current_path = os.path.join(base_download_root, self.catalog, first_level_folder)
            self.metadata_folder = current_path

        elif self.catalog == 'Tag':
            first_level_folder = self._sanitize_filename(self.item_id)
            current_path = os.path.join(base_download_root, self.catalog, first_level_folder)
            self.metadata_folder = current_path

        elif self.catalog == 'Ranking':
            current_path = self.custom_download_path
            self.metadata_folder = current_path

        if pid_option != '无':
            second_level_folder = ""
            if pid_option == 'PID':
                second_level_folder = self._sanitize_filename(work_details.get('work_id', 'Unknown_PID'))
            else:
                second_level_folder = self._sanitize_filename(work_details.get('title', 'Unknown_Title'))

            current_path = os.path.join(current_path, second_level_folder)

        try:
            os.makedirs(current_path, exist_ok=True)
        except OSError as e:
            print(f"Error creating download directory {current_path}: {e}")
            self.progress_signal.emit(self.item_id, 0, 0, f"创建目录失败: {e}", self.catalog)
            return None

        return current_path

    def _save_metadata_file(self):
        if self.catalog == 'Ranking':
            return  # Ranking metadata is handled by Ranking class

        all_downloaded_ids = self.original_existing_image_ids.union(set(self.downloaded_work_ids))
        try:
            sorted_all_downloaded_ids = sorted(list(all_downloaded_ids), key=lambda x: int(x))
        except ValueError:
            sorted_all_downloaded_ids = sorted(list(all_downloaded_ids))

        if not sorted_all_downloaded_ids and self.item_type == 'user':
            self.progress_signal.emit(self.item_id, self.total_works, self.total_works,
                                      f"【{self.item_id}】元数据保存跳过: 没有新的或已存在的作品ID。", self.catalog)
            return

        if not self.metadata_folder:
            return

        meta = {
            "quantity": len(sorted_all_downloaded_ids),
            "image_id": sorted_all_downloaded_ids,
            "download_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base_path": os.path.abspath(self.config.get('download_path', {}).get('base_path', './downloads')),
            "uid_option": self.config.get('download_path', {}).get('uid_option', 'UID'),
            "pid_option": self.config.get('download_path', {}).get('pid_option', '无')
        }

        if self.item_type == 'user':
            meta["user_name"] = self.entity_name if self.entity_name != "Unknown" else self.item_id
            meta["user_id"] = self.item_id
        elif self.item_type == 'tag':
            meta["tag_name"] = self.item_id
            meta["tag_id"] = self.item_id
            meta["age_mode"] = self.age_mode

        meta_path = os.path.join(self.metadata_folder, f"{self.item_id}.json")
        try:
            os.makedirs(os.path.dirname(meta_path), exist_ok=True)
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self.progress_signal.emit(self.item_id, self.total_works, self.total_works,
                                      f"【{self.item_id}】元数据保存成功", self.catalog)
        except Exception as e:
            self.progress_signal.emit(self.item_id, self.total_works, self.total_works,
                                      f"【{self.item_id}】元数据保存失败: {e}", self.catalog)

    def stop(self):
        self.resume();
        self.stop_event.set()

    def pause(self):
        self.pause_event.set()

    def resume(self):
        self.pause_event.clear()

    def check_pause(self):
        while self.pause_event.is_set():
            if self.stop_event.is_set(): break
            time.sleep(0.5)


class DownloadManager(QObject):
    # 修改信号签名，增加 catalog 参数
    task_progress = pyqtSignal(str, int, int, str, str);  # item_id, completed, total, status, catalog
    task_finished = pyqtSignal(str, str);  # item_id, catalog
    speed_updated = pyqtSignal(float)
    _instance, _lock, _initialized = None, threading.Lock(), False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None: cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, parent=None):
        if self._initialized: return
        super().__init__(parent)
        self.active_threads, self.config = {}, {};
        self.bytes_in_second = 0;
        self.byte_lock = threading.Lock()
        self.speed_timer = None;
        self._initialized = True
        self.task_queue = []
        self.active_tasks = {}

    def init_timer(self):
        if self.speed_timer is None:
            self.speed_timer = QTimer(self);
            self.speed_timer.timeout.connect(self._calculate_speed);
            self.speed_timer.start(1000)

    def load_config(self, config_data):
        self.config = config_data;
        cookie_manager.load_cookies(config_data)

    def add_task(self, item_id, catalog, item_type='user', age_mode='all', existing_image_ids=None,
                 completion_strategy='default', custom_path=None, ranking_type_name=None, ranking_date_str=None):
        if self.is_task_queued_or_active(item_id):
            return False

        task_data = {
            'item_id': item_id,
            'catalog': catalog,
            'item_type': item_type,
            'age_mode': age_mode,
            'existing_image_ids': existing_image_ids,
            'completion_strategy': completion_strategy,
            'custom_path': custom_path,
            'ranking_type_name': ranking_type_name,
            'ranking_date_str': ranking_date_str
        }
        self.task_queue.append(task_data)
        self._start_next_task()
        return True

    def _start_next_task(self):
        max_threads = int(self.config.get('thread_count', 5))
        if len(self.active_tasks) >= max_threads:
            return

        if not self.task_queue:
            return

        task_data = self.task_queue.pop(0)
        item_id = task_data['item_id']

        thread = DownloadThread(
            item_id=item_id,
            config=self.config,
            catalog=task_data['catalog'],
            item_type=task_data['item_type'],
            age_mode=task_data['age_mode'],
            existing_image_ids=task_data['existing_image_ids'],
            completion_strategy=task_data['completion_strategy'],
            custom_path=task_data['custom_path'],
            ranking_type_name=task_data['ranking_type_name'],
            ranking_date_str=task_data['ranking_date_str']
        )
        # 连接信号时，槽函数需要匹配新的信号签名
        thread.progress_signal.connect(self.task_progress.emit)
        thread.finished_signal.connect(self._on_thread_finished)
        thread.chunk_downloaded.connect(self._on_chunk_downloaded)
        thread.start()
        self.active_tasks[item_id] = thread

    def _on_thread_finished(self, item_id, catalog):  # 接收 catalog 参数
        if item_id in self.active_tasks:
            thread = self.active_tasks.pop(item_id)
            thread.quit()
            thread.wait()
            self.task_finished.emit(item_id, catalog)  # 传递 catalog
            self._start_next_task()

    def _on_chunk_downloaded(self, bytes_downloaded):
        with self.byte_lock:
            self.bytes_in_second += bytes_downloaded

    def _calculate_speed(self):
        with self.byte_lock:
            speed = self.bytes_in_second
            self.bytes_in_second = 0
        self.speed_updated.emit(speed)

    def is_task_queued_or_active(self, item_id):
        if item_id in self.active_tasks:
            return True
        for task in self.task_queue:
            if task['item_id'] == item_id:
                return True
        return False

    def pause_download(self, item_id):
        if item_id in self.active_tasks:
            self.active_tasks[item_id].pause()

    def resume_download(self, item_id):
        if item_id in self.active_tasks:
            self.active_tasks[item_id].resume()

    def stop_download(self, item_id):
        if item_id in self.active_tasks:
            self.active_tasks[item_id].stop()
            self.active_tasks.pop(item_id, None)
        self.task_queue = [task for task in self.task_queue if task['item_id'] != item_id]
        self._start_next_task()

    def get_active_and_queued_tasks(self):
        active_ids = list(self.active_tasks.keys())
        queued_ids = [task['item_id'] for task in self.task_queue]
        return active_ids + queued_ids

    def get_active_and_queued_ranking_tasks(self):
        ranking_tasks = []
        for item_id, thread in self.active_tasks.items():
            if thread.catalog == 'Ranking':
                ranking_tasks.append(item_id)
        for task_data in self.task_queue:
            if task_data['catalog'] == 'Ranking':
                ranking_tasks.append(task_data['item_id'])
        return ranking_tasks

    def pause_all_ranking_downloads(self):
        for item_id, thread in self.active_tasks.items():
            if thread.catalog == 'Ranking':
                thread.pause()

    def resume_all_ranking_downloads(self):
        for item_id, thread in self.active_tasks.items():
            if thread.catalog == 'Ranking':
                thread.resume()

    def stop_all_ranking_downloads(self):
        items_to_stop = [item_id for item_id, thread in self.active_tasks.items() if thread.catalog == 'Ranking']
        for item_id in items_to_stop:
            self.stop_download(item_id)

        self.task_queue = [task for task in self.task_queue if task['catalog'] != 'Ranking']
        self._start_next_task()


download_manager = DownloadManager()
