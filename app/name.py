# name.py
import re
import json
import requests
import os


def get_user_profile(cookie: str, proxy_settings: dict) -> tuple:
    """
    根据Pixiv cookie获取用户名和头像信息

    参数:
        cookie (str): Pixiv网站的cookie字符串
        proxy_settings (dict): 代理设置字典

    返回: tuple: (状态码, 用户名, 头像本地路径)
    """
    try:
        # 设置代理 - 使用传入的代理设置字典
        proxies = setup_proxies(proxy_settings)
        print(f"代理设置: {proxies}")  # 调试信息

        # 请求Pixiv排名页面
        url = "https://www.pixiv.net/ranking.php"
        headers = {
            "cookie": cookie,
            "referer": "https://www.pixiv.net",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36"
        }

        response = requests.get(url, headers=headers, timeout=(5, 5), proxies=proxies)

        if response.status_code != 200:
            print(f"请求失败，状态码: {response.status_code}")  # 调试信息
            return ("proxies_no", "", "")

        # 从响应中提取用户数据
        if match := re.search(r'"userData":({.*?})', response.text, re.DOTALL):
            user_data = json.loads(match.group(1))
            name = user_data.get('name', '')
            image_url = user_data.get('profileImgBig', '')
            print(f"提取到用户数据: name={name}, image_url={image_url}")  # 调试信息

            # 检查是否为有效用户名
            if name and name != 'shirakaba':
                # 下载并保存头像
                profile_path = save_profile_image(name, image_url, headers, proxies)
                if profile_path:
                    return ("ok", name, profile_path)
                else:
                    return ("ok", name, "")  # 返回用户名但无头像路径
            else:
                return ("login_no", name, "")
        else:
            print("未找到userData字段")  # 调试信息
            return ("cookie_no", "", "")
    except requests.exceptions.Timeout:
        print("请求超时")  # 调试信息
        return ("proxies_no", "", "")
    except requests.exceptions.ProxyError as e:
        print(f"代理错误: {e}")  # 调试信息
        return ("proxies_no", "", "")
    except Exception as e:
        print(f"获取用户信息时发生错误: {e}")  # 调试信息
        return ("cookie_no", "", "")


def save_profile_image(name: str, image_url: str, headers: dict, proxies: dict) -> str:
    """
    下载并保存用户头像

    参数:
        name (str): 用户名
        image_url (str): 头像URL
        headers (dict): 请求头
        proxies (dict): 代理设置

    返回:
        str: 头像本地路径（如果成功），否则返回空字符串
    """
    if not name or not image_url:
        print("无效的用户名或图像URL")  # 调试信息
        return ""

    try:
        # 创建存储目录
        image_dir = os.path.join(os.getcwd(), "user", "name")
        os.makedirs(image_dir, exist_ok=True)

        # 生成文件名（用户名+扩展名）
        _, ext = os.path.splitext(image_url)
        # 确保扩展名有效
        ext = ext if ext and len(ext) <= 5 else '.jpg'
        filename = f"{name}{ext}"
        filepath = os.path.join(image_dir, filename)
        filepath = filepath.replace('\\', '/')
        print(f"保存头像到: {filepath}")  # 调试信息

        # 下载头像
        response = requests.get(image_url, headers=headers, timeout=(10, 10), proxies=proxies)

        if response.status_code == 200:
            # 保存文件
            with open(filepath, "wb") as f:
                f.write(response.content)
            print(f"头像保存成功: {filepath}")  # 调试信息
            return filepath
        else:
            print(f"下载头像失败，状态码: {response.status_code}")  # 调试信息
            return ""
    except Exception as e:
        print(f"保存头像时发生错误: {e}")  # 调试信息
        return ""


def setup_proxies(proxy_settings: dict):
    """
    从代理设置字典构建代理配置
    参数: proxy_settings (dict): 代理设置字典
    """
    if not proxy_settings:
        return None

    proxy_type = proxy_settings.get('type', 0)
    proxy_address = proxy_settings.get('address', '')
    proxy_port = proxy_settings.get('port', '')

    # 以下逻辑与之前类似，但不再访问setting对象
    if proxy_type == 0:  # 不使用代理
        print("不使用代理")
        return None

    elif proxy_type == 1:  # HTTP代理
        if not proxy_address or not proxy_port:
            print("HTTP代理配置不完整")
            return None

        # 确保地址有协议前缀
        if not proxy_address.startswith(('http://', 'https://')):
            proxy_address = f"http://{proxy_address}"

        proxy_value = f"{proxy_address}:{proxy_port}"
        print(f"使用HTTP代理: {proxy_value}")
        return {"http": proxy_value, "https": proxy_value}

    elif proxy_type == 2:  # SOCKS5代理
        if not proxy_address or not proxy_port:
            print("SOCKS5代理配置不完整")
            return None

        try:
            # 确保端口是整数
            proxy_port = int(proxy_port)
        except ValueError:
            print(f"无效的SOCKS5端口: {proxy_port}")
            return None

        print(f"使用SOCKS5代理: socks5://{proxy_address}:{proxy_port}")
        return {
            "http": f"socks5://{proxy_address}:{proxy_port}",
            "https": f"socks5://{proxy_address}:{proxy_port}"
        }

    else:
        print(f"未知的代理类型: {proxy_type}")
        return None

