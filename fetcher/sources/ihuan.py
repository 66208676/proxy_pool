# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     ihuan.py
   Description :   小幻代理代理源
   Author :        JHao
   date：          2026/5/31
-------------------------------------------------
   Change Activity:
                   2026/05/31:
-------------------------------------------------
"""
__author__ = 'JHao'

from lxml import etree
import requests

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest
from util.fetchProxy import getFetchProxies


class IhuanFetcher(BaseFetcher):
    """小幻代理 https://ip.ihuan.me/"""

    name = "ihuan"
    url = "https://ip.ihuan.me/"
    overseas = False
    enabled = True

    def fetch(self):
        wb = WebRequest()
        session = requests.session()
        headers = wb.header
        # 显式带上传出代理上下文：否则 session 默认 trust_env 会读环境变量里的
        # 本地正向代理，既绕过分流控制，也会让"直连"变成走代理。
        proxies = getFetchProxies()
        session.get(self.url, headers=headers, verify=False,
                    proxies=proxies)  # 必须先请求一次获取cookie
        res = session.get(self.url, headers=headers, verify=False,
                          proxies=proxies)
        tree = etree.HTML(res.text)
        for item in tree.xpath("//table[@class='table table-hover table-bordered']//tr"):
            ip = "".join(item.xpath("./td[1]//text()")).strip()
            port = "".join(item.xpath("./td[2]//text()")).strip()
            if ip and port:
                yield "%s:%s" % (ip, port)


if __name__ == '__main__':
    for proxy in IhuanFetcher().fetch():
        print(proxy)
