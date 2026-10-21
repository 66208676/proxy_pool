# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     proxio.py
   Description :   Proxio proxy-list（走 jsDelivr CDN）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：jsDelivr CDN 直连 200，https.txt 6699 条。
   官方仓库约每 20 分钟刷新一次；all.json 含 country/anonymity/latency/uptime 等元数据。
   默认 enabled=False —— 只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest

CDN = "https://cdn.jsdelivr.net/gh/proxio-io/proxy-list@main"


class ProxioFetcher(BaseFetcher):
    """Proxio 代理列表"""

    name = "proxio"
    url = "https://github.com/proxio-io/proxy-list"
    enabled = False
    overseas = False

    URLS = (CDN + "/https.txt", CDN + "/http.txt")

    def fetch(self):
        proxies = []
        for url in self.URLS:
            r = WebRequest().get(url, timeout=20, retry_time=2)
            proxies += self.parseProxiesFromText(r.text)
        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    print("proxio", sum(1 for _ in ProxioFetcher().fetch()), "条")
