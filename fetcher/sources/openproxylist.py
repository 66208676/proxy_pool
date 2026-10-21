# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     openproxylist.py
   Description :   OpenProxyList 免费代理源（纯文本 ip:port）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：国内直连 200 可达，返回纯文本，每行 ip:port。
   默认 enabled=False —— 不进现有调度器，只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class OpenProxyListFetcher(BaseFetcher):
    """OpenProxyList HTTP 列表"""

    name = "openproxylist"
    url = "https://api.openproxylist.xyz/http.txt"
    enabled = False
    overseas = False

    # 同时取 http / https 两份清单：https.txt 实测 4529 条，
    # 能显著提高池子里可响应 type=https 的代理比例。
    URLS = ("https://api.openproxylist.xyz/http.txt",
            "https://api.openproxylist.xyz/https.txt")

    def fetch(self):
        proxies = []
        for url in self.URLS:
            r = WebRequest().get(url, timeout=20, retry_time=2)
            proxies += self.parseProxiesFromText(r.text)
        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    for p in OpenProxyListFetcher().fetch():
        print(p)
