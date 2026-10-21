# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     scdn.py
   Description :   SCDN代理源
   Author :        JHao
   date：          2026/5/31
-------------------------------------------------
   Change Activity:
                   2026/05/31:
-------------------------------------------------
"""
__author__ = 'JHao'

import re

from lxml import etree

from fetcher.baseFetcher import BaseFetcher
from handler.logHandler import LogHandler
from util.webRequest import WebRequest

logger = LogHandler("fetcher")


class ScdnFetcher(BaseFetcher):
    """SCDN 代理接口 https://proxy.scdn.io/"""

    name = "scdn"
    url = "https://proxy.scdn.io/"
    overseas = True

    PAGES = 3  # per_page=100，抓 3 页

    def fetch(self):
        found = []
        for page in range(1, self.PAGES + 1):
            found += self._fetch_page(page)
        for proxy in self.yieldUniqueProxies(found):
            yield proxy

    def _fetch_page(self, page):
        url = ("https://proxy.scdn.io/get_proxies.php?"
               "protocol=&country=&per_page=100&page=%d" % page)
        r = WebRequest().get(url, timeout=10, retry_time=1, verify=False)
        proxies = []
        try:
            data = r.json
            table_html = data.get("table_html") if isinstance(data, dict) else ""
            if table_html:
                tree = etree.HTML("<table>%s</table>" % table_html)
                for tr in tree.xpath("//tr"):
                    cells = [" ".join(td.xpath(".//text()")).strip() for td in tr.xpath("./td")]
                    if len(cells) >= 2:
                        ip_match = re.match(r'^\d{1,3}(?:\.\d{1,3}){3}$', cells[0])
                        port_match = re.match(r'^\d{2,5}$', cells[1])
                        if ip_match and port_match:
                            proxies.append("%s:%s" % (cells[0], cells[1]))

            if not proxies:
                items = data.get("data", []) if isinstance(data, dict) else []
                for item in items:
                    ip = item.get("ip", "")
                    port = item.get("port", "")
                    if ip and port:
                        proxies.append("%s:%s" % (ip, port))
            if not proxies:
                proxies = self.parseProxiesFromText(r.text)
        except Exception as e:
            logger.error("ProxyFetch - scdn: %s" % e)
        return proxies


if __name__ == '__main__':
    for proxy in ScdnFetcher().fetch():
        print(proxy)
