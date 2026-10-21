# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     fetchProxy.py
   Description :   抓取阶段的出口代理上下文（线程隔离）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增，用于让"国外代理源走出口代理、国内代理源直连"
-------------------------------------------------
设计要点：
  1. 只在"抓取线程"里生效。通过 threading.local 传递，API 线程、校验线程
     拿不到上下文 -> WebRequest 行为完全不变，不影响现有代理池与接口。
  2. 直连用 {"http": None, "https": None} 而不是不传参数：
     requests 默认 trust_env=True 会读取 HTTP_PROXY 环境变量，
     本机恰好有本地正向代理，不显式屏蔽就不是"直连"。
"""
__author__ = 'zhaoqi'

import os
import threading

_local = threading.local()

# 环境变量取值顺序
_ENV_KEYS = ("FETCH_PROXY_URL", "https_proxy", "HTTPS_PROXY",
             "http_proxy", "HTTP_PROXY")


def resolveUpstreamProxy():
    """
    出口代理地址（用于访问国外代理源）。
    优先 setting.FETCH_PROXY_URL，留空则回退环境变量。
    """
    value = ""
    try:
        import setting
        value = getattr(setting, "FETCH_PROXY_URL", "") or ""
    except Exception:
        value = ""
    if value:
        return value.strip()
    for key in _ENV_KEYS:
        v = os.environ.get(key, "")
        if v:
            return v.strip()
    return ""


def _normalize(url):
    """requests 的 proxies 值必须带 scheme；池内代理形如 user:pass@ip:port 需补全"""
    if url and "://" not in url:
        return "http://" + url
    return url


def setFetchProxy(value):
    """
    设置当前线程抓取时的出口。
        value = ""            -> 强制直连
        value = "host:port"   -> 固定单个出口
        value = [a, b, c]     -> 多出口，每次请求轮换（分散源站限流风险）
    """
    if isinstance(value, (list, tuple, set)):
        _local.pool = [_normalize(v) for v in value if v]
        _local.index = 0
        _local.proxy = None
    else:
        _local.pool = None
        _local.proxy = value


def clearFetchProxy():
    """清除当前线程的抓取上下文"""
    _local.proxy = None


def getFetchProxies():
    """
    返回传给 requests 的 proxies 参数。
        None                      -> 不在抓取上下文，保持 requests 默认行为
                                     （API / 代理校验线程走这里，不受影响）
        {"http": None, ...}       -> 强制直连，屏蔽环境代理
        {"http": url, "https": url} -> 走出口代理
    """
    pool = getattr(_local, "pool", None)
    if pool:
        idx = getattr(_local, "index", 0)
        url = pool[idx % len(pool)]
        _local.index = idx + 1
        return {"http": url, "https": url}

    url = getattr(_local, "proxy", None)
    if url is None:
        return None
    if not url:
        return {"http": None, "https": None}
    url = _normalize(url)
    return {"http": url, "https": url}
