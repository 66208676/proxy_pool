# -*- coding: utf-8 -*-
# !/usr/bin/env python
"""
-------------------------------------------------
   File Name：     ProxyApi.py
   Description :   WebApi
   Author :       JHao
   date：          2016/12/4
-------------------------------------------------
   Change Activity:
                   2016/12/04: WebApi
                   2019/08/14: 集成Gunicorn启动方式
                   2020/06/23: 新增pop接口
                   2022/07/21: 更新count接口
-------------------------------------------------
"""
__author__ = 'JHao'

import os
import platform
import re
import time

from werkzeug.wrappers import Response
from flask import Flask, jsonify, request

from util.six import iteritems
from helper.proxy import Proxy
from handler.proxyHandler import ProxyHandler
from handler.configHandler import ConfigHandler

app = Flask(__name__)
conf = ConfigHandler()
proxy_handler = ProxyHandler()

# ---------------------------------------------------------------- 控制台相关
# 新增：/dashboard 系列接口（本地控制台 UI），不改动原有 API 行为。
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "log")

# 实测出口 IP 用的回显地址。固定写死，不接受调用方传入 URL，
# 避免这个接口被当成任意请求转发器。
ECHO_URL = "https://myip.ipip.net"
IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


def _tail_lines(path, nbytes=200000):
    """读文件末尾若干字节并按行切分（日志文件可能很大）。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > nbytes:
                f.seek(-nbytes, os.SEEK_END)
                f.readline()  # 丢掉可能被截断的半行
            return f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return []


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _scheduler_state():
    """从 log/ 和 PID 文件推断调度器状态，不需要额外的进程间通信。"""
    pid = None
    try:
        with open(os.path.join(LOG_DIR, "schedule.pid")) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        pass

    started = next_run = last_check = None
    for line in _tail_lines(os.path.join(LOG_DIR, "scheduler.log")):
        if "Scheduler started" in line:
            started = line[:19]
        m = re.search(r"Next wakeup is due at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m:
            next_run = m.group(1)

    for line in reversed(_tail_lines(os.path.join(LOG_DIR, "checker.log"))):
        m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m:
            last_check = m.group(1)
            break

    return {
        "running": _pid_alive(pid),
        "pid": pid,
        "started": started,
        "next_run": next_run,
        "last_check": last_check,
    }


@app.route("/dashboard")
def dashboard():
    """本地控制台页面（与 API 同源，避免浏览器跨域限制）。"""
    path = os.path.join(API_DIR, "dashboard.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return Response("dashboard.html 缺失", status=500, mimetype="text/plain")
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/dashboard/stats")
def dashboard_stats():
    proxies = proxy_handler.getAll()
    https_count = sum(1 for p in proxies if p.https)
    sources = {}
    for p in proxies:
        for s in (p.source or "").split("/"):
            if s:
                sources[s] = sources.get(s, 0) + 1
    return {
        "count": len(proxies),
        "https": https_count,
        "http": len(proxies) - https_count,
        "sources": sources,
        "scheduler": _scheduler_state(),
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.route("/dashboard/proxies")
def dashboard_proxies():
    """分页 + 搜索的代理列表。3400 条一次性传给浏览器太重，所以服务端分页。"""
    keyword = request.args.get("q", "").strip().lower()
    only_https = request.args.get("https", "").lower() == "true"
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        size = min(500, max(10, int(request.args.get("size", 50))))
    except ValueError:
        size = 50

    rows = proxy_handler.getAll()
    if only_https:
        rows = [p for p in rows if p.https]
    if keyword:
        rows = [p for p in rows if keyword in (p.proxy or "").lower()]

    total = len(rows)
    start = (page - 1) * size
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [p.to_dict for p in rows[start:start + size]],
    }


@app.route("/dashboard/test")
def dashboard_test():
    """通过指定代理真实发一次请求，返回出口 IP。用于验证代理是否真的可用。"""
    target = request.args.get("proxy", "").strip()
    if not target:
        return {"ok": False, "error": "缺少 proxy 参数"}

    import requests

    session = requests.Session()
    session.trust_env = False  # 忽略本机透明代理
    url = "http://" + target
    t0 = time.time()
    try:
        resp = session.get(ECHO_URL, timeout=15,
                           proxies={"http": url, "https": url})
        match = IP_RE.search(resp.text)
        return {
            "ok": True,
            "exit_ip": match.group(1) if match else "",
            "raw": resp.text.strip(),
            "elapsed": round(time.time() - t0, 2),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "elapsed": round(time.time() - t0, 2),
        }


class JsonResponse(Response):
    @classmethod
    def force_type(cls, response, environ=None):
        if isinstance(response, (dict, list)):
            response = jsonify(response)

        return super(JsonResponse, cls).force_type(response, environ)


app.response_class = JsonResponse

api_list = [
    {"url": "/dashboard", "params": "", "desc": "本地控制台（网页 UI）"},
    {"url": "/get", "params": "type: ''https'|''", "desc": "get a proxy"},
    {"url": "/pop", "params": "", "desc": "get and delete a proxy"},
    {"url": "/delete", "params": "proxy: 'e.g. 127.0.0.1:8080'", "desc": "delete an unable proxy"},
    {"url": "/all", "params": "type: ''https'|''", "desc": "get all proxy from proxy pool"},
    {"url": "/count", "params": "", "desc": "return proxy count"}
    # 'refresh': 'refresh proxy pool',
]


@app.route('/')
def index():
    return {'url': api_list}


@app.route('/get/')
def get():
    https = request.args.get("type", "").lower() == 'https'
    proxy = proxy_handler.get(https)
    return proxy.to_dict if proxy else {"code": 0, "src": "no proxy"}


@app.route('/pop/')
def pop():
    https = request.args.get("type", "").lower() == 'https'
    proxy = proxy_handler.pop(https)
    return proxy.to_dict if proxy else {"code": 0, "src": "no proxy"}


@app.route('/refresh/')
def refresh():
    # TODO refresh会有守护程序定时执行，由api直接调用性能较差，暂不使用
    return 'success'


@app.route('/all/')
def getAll():
    https = request.args.get("type", "").lower() == 'https'
    proxies = proxy_handler.getAll(https)
    return jsonify([_.to_dict for _ in proxies])


@app.route('/delete/', methods=['GET'])
def delete():
    proxy = request.args.get('proxy')
    status = proxy_handler.delete(Proxy(proxy))
    return {"code": 0, "src": status}


@app.route('/count/')
def getCount():
    proxies = proxy_handler.getAll()
    http_type_dict = {}
    source_dict = {}
    for proxy in proxies:
        http_type = 'https' if proxy.https else 'http'
        http_type_dict[http_type] = http_type_dict.get(http_type, 0) + 1
        for source in proxy.source.split('/'):
            source_dict[source] = source_dict.get(source, 0) + 1
    return {"http_type": http_type_dict, "source": source_dict, "count": len(proxies)}


def runFlask():
    if platform.system() == "Windows":
        # 默认单线程: 8 个 worker 并发打 /get/ 会被串行化, 响应超爬虫侧 timeout=3s
        # 即触发"代理池不可用, 本次直连"。threaded=True 让每请求开一线程, 并发取代理不再排队。
        app.run(host=conf.serverHost, port=conf.serverPort, threaded=True)
    else:
        import gunicorn.app.base

        class StandaloneApplication(gunicorn.app.base.BaseApplication):

            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super(StandaloneApplication, self).__init__()

            def load_config(self):
                _config = dict([(key, value) for key, value in iteritems(self.options)
                                if key in self.cfg.settings and value is not None])
                for key, value in iteritems(_config):
                    self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        _options = {
            'bind': '%s:%s' % (conf.serverHost, conf.serverPort),
            'workers': 4,
            'accesslog': '-',  # log to stdout
            'access_log_format': '%(h)s %(l)s %(t)s "%(r)s" %(s)s "%(a)s"'
        }
        StandaloneApplication(app, _options).run()


if __name__ == '__main__':
    runFlask()
