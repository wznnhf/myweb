"""Start the local study room from the macOS double-click launcher."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765/'
HTTP = build_opener(ProxyHandler({}))


def ready():
    try:
        with HTTP.open(URL + 'api/library?subject=math', timeout=1) as response:
            data = json.load(response)
        return data.get('subject') == 'math' and isinstance(data.get('papers'), list)
    except (OSError, ValueError):
        return False


def open_page():
    subprocess.run(['/usr/bin/open', URL], check=True)


def main():
    if ready():
        print('拾题已经在运行，正在打开网页。', flush=True)
        open_page()
        return 0

    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8765)) == 0:
            print('8765 端口被其他程序占用，请关闭占用程序后再次启动拾题。')
            return 1

    env = os.environ.copy()
    env.pop('CUOTI_DATA_DIR', None)
    process = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'server:app',
         '--host', '127.0.0.1', '--port', '8765'],
        cwd=ROOT, env=env,
    )
    try:
        print('正在启动拾题…', flush=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                print('拾题启动失败，请查看上方提示。', flush=True)
                return 1
            if ready():
                print('拾题已启动：' + URL, flush=True)
                print('使用期间请保留这个终端窗口。按 Control+C 可停止服务。', flush=True)
                open_page()
                return process.wait()
            time.sleep(0.2)
        print('启动超时，请查看上方提示后重试。', flush=True)
        return 1
    except KeyboardInterrupt:
        print('\n拾题已停止，笔记和收藏保存在本机。', flush=True)
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    sys.exit(main())
