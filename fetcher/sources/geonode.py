# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     geonode.py
   Description :   Geonode代理源
   Author :        JHao
   date：          2026/5/31
-------------------------------------------------
   Change Activity:
                   2026/05/31:
-------------------------------------------------
"""
__author__ = 'JHao'

from fetcher.baseFetcher import BaseFetcher
from handler.logHandler import LogHandler
from util.webRequest import WebRequest

logger = LogHandler("fetcher")


class GeonodeFetcher(BaseFetcher):
    """Geonode Free Proxy https://geonode.com/"""

    name = "geonode"
    url = "https://geonode.com/"
    overseas = True

    PAGES = 3  # limit=100，抓 3 页

    def fetch(self):
        found = []
        for page in range(1, self.PAGES + 1):
            found += self._fetch_page(page)
        for proxy in self.yieldUniqueProxies(found):
            yield proxy

    def _fetch_page(self, page):
        url = ("https://proxylist.geonode.com/api/proxy-list?"
               "filterLastChecked=10&page=%d&limit=100"
               "&sort_by=lastChecked&sort_type=desc" % page)
        r = WebRequest().get(url, timeout=10, retry_time=1, verify=False)
        proxies = []
        try:
            for item in r.json.get("data", []):
                ip = item.get("ip", "")
                port = item.get("port", "")
                if ip and port:
                    proxies.append("%s:%s" % (ip, port))
            if not proxies:
                proxies = self.parseProxiesFromText(r.text)
        except Exception as e:
            logger.error("ProxyFetch - geonode: %s" % e)
        return proxies


if __name__ == '__main__':
    for proxy in GeonodeFetcher().fetch():
        print(proxy)