# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     ip3366.py
   Description :   云代理代理源
   Author :        JHao
   date：          2026/5/31
-------------------------------------------------
   Change Activity:
                   2026/05/31:
-------------------------------------------------
"""
__author__ = 'JHao'

import re

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class Ip3366Fetcher(BaseFetcher):
    """云代理 http://www.ip3366.net/"""

    name = "ip3366"
    url = "http://www.ip3366.net/"
    overseas = True

    # stype=1/2 两种类型 × page 1..3；再多会超过单源 45s 的抓取预算
    PAGES = 3
    PATTERN = re.compile(
        r'<td>(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})</td>[\s\S]*?<td>(\d+)</td>')

    def fetch(self):
        found = []
        for stype in (1, 2):
            for page in range(1, self.PAGES + 1):
                url = "http://www.ip3366.net/free/?stype=%d&page=%d" % (stype, page)
                r = WebRequest().get(url, timeout=15)
                found += [":".join(m) for m in self.PATTERN.findall(r.text or "")]
        for proxy in self.yieldUniqueProxies(found):
            yield proxy


if __name__ == '__main__':
    for proxy in Ip3366Fetcher().fetch():
        print(proxy)