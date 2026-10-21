# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     moleway.py
   Description :   Moleway Free-Proxy-List（走 jsDelivr CDN）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：raw.githubusercontent.com 被 Cloudflare 拦(error 1033)，
   但 jsDelivr CDN 直连 200。https.txt 实测 136 条。
   该源的 https.txt 是**真正验证过 HTTPS tunnelling** 的 HTTP 代理，
   不是把 HTTP 代理标成 HTTPS，质量高于同类。
   默认 enabled=False —— 只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest

CDN = "https://cdn.jsdelivr.net/gh/Moleway/Free-Proxy-List@main"


class MolewayFetcher(BaseFetcher):
    """Moleway 免费代理列表"""

    name = "moleway"
    url = "https://github.com/Moleway/Free-Proxy-List"
    enabled = False
    overseas = False  # jsDelivr CDN 国内直连可达

    URLS = (CDN + "/https.txt", CDN + "/http.txt")

    def fetch(self):
        proxies = []
        for url in self.URLS:
            r = WebRequest().get(url, timeout=20, retry_time=2)
            proxies += self.parseProxiesFromText(r.text)
        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    print("moleway", sum(1 for _ in MolewayFetcher().fetch()), "条")
