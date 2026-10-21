# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     databay.py
   Description :   Databay Labs free-proxy-list（走 jsDelivr CDN）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：jsDelivr CDN 直连 200，http.txt 6357 条。
   注意：该仓库默认分支是 **master**（不是 main）。约 5 分钟更新一次，IP:PORT 纯文本。
   默认 enabled=False —— 只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class DatabayFetcher(BaseFetcher):
    """Databay Labs 免费代理列表"""

    name = "databay"
    url = "https://github.com/databay-labs/free-proxy-list"
    enabled = False
    overseas = False

    URLS = ("https://cdn.jsdelivr.net/gh/databay-labs/free-proxy-list@master/http.txt",)

    def fetch(self):
        proxies = []
        for url in self.URLS:
            r = WebRequest().get(url, timeout=20, retry_time=2)
            proxies += self.parseProxiesFromText(r.text)
        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    print("databay", sum(1 for _ in DatabayFetcher().fetch()), "条")
