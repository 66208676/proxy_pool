# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     cyberh4ck3r.py
   Description :   cyberh4ck3r/free-proxy-list（走 jsDelivr CDN）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：jsDelivr CDN 直连 200，unchecked/http-proxies.txt 2975 条。
   注意：目录下是 **unchecked**（未经健康检查的原始代理），可用率偏低，
   定位为"广撒网备用源"，必须经本地校验后才入库。
   默认 enabled=False —— 只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest

CDN = ("https://cdn.jsdelivr.net/gh/cyberh4ck3r/free-proxy-list@main"
       "/proxies/unchecked")


class Cyberh4ck3rFetcher(BaseFetcher):
    """cyberh4ck3r 免费代理列表（unchecked）"""

    name = "cyberh4ck3r"
    url = "https://github.com/cyberh4ck3r/free-proxy-list"
    enabled = False
    overseas = False

    URLS = (CDN + "/https-proxies.txt", CDN + "/http-proxies.txt")

    def fetch(self):
        proxies = []
        for url in self.URLS:
            r = WebRequest().get(url, timeout=20, retry_time=2)
            proxies += self.parseProxiesFromText(r.text)
        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    print("cyberh4ck3r", sum(1 for _ in Cyberh4ck3rFetcher().fetch()), "条")
