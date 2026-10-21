# -*- coding: utf-8 -*-
"""
clear_invalid_sweep.py (v2, safe)
仅删除“确定性无效”的代理：407 认证失败 / 连接被拒 / 非 200。
对“超时”这一类模糊失败不做删除（交给 proxy_pool 调度器的 use-check 后续处理），
避免误删高延迟但可用的代理。

操作对象仅为 Redis `use_proxy` 哈希，不触碰任何文件数据。
"""
import redis
import urllib3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests import head
from requests.exceptions import Timeout

urllib3.disable_warnings()
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_PWD = "123456"
KEY = "use_proxy"

TARGETS = ["https://www.qq.com", "https://www.baidu.com", "http://httpbin.org"]
TIMEOUT = 6
CONCURRENCY = 100
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) Gecko/20100101 Firefox/34.0"}


def pick_target():
    for t in TARGETS:
        try:
            head(t, timeout=5, verify=False, headers=HEADERS)
            return t
        except Exception:
            continue
    return TARGETS[0]


def classify(proxy, target):
    proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    try:
        r = head(target, proxies=proxies, timeout=TIMEOUT, verify=False, headers=HEADERS)
        return "ok" if r.status_code == 200 else "fail"
    except Timeout:
        return "timeout"   # 模糊：保留，交调度器后续处理
    except Exception:
        return "fail"      # 确定性无效：407/连接被拒/其他 -> 删除


def check_one(proxy, target):
    c = classify(proxy, target)
    return proxy, (c != "fail"), c


def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PWD,
                    decode_responses=True, protocol=2)
    target = pick_target()
    print(f"[clear_invalid] target={target} redis_ok={r.ping()} key={KEY}", flush=True)

    members = list(r.hkeys(KEY))
    total = len(members)
    print(f"[clear_invalid] loaded {total} proxies", flush=True)

    to_delete = set()
    checked = 0
    kinds = {"ok": 0, "fail": 0, "timeout": 0}
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = [ex.submit(check_one, p, target) for p in members]
        for f in as_completed(futs):
            proxy, keep, status = f.result()
            checked += 1
            kinds[status] += 1
            if not keep:
                to_delete.add(proxy)
            if checked % 3000 == 0:
                print(f"[clear_invalid] checked {checked}/{total}, invalid_so_far={len(to_delete)}", flush=True)

    print(f"[clear_invalid] done. checked={checked}, kinds={kinds}", flush=True)
    print(f"[clear_invalid] invalid_to_delete(fail)={len(to_delete)}", flush=True)
    if to_delete:
        pipe = r.pipeline()
        for p in to_delete:
            pipe.hdel(KEY, p)
        pipe.execute()
        print(f"[clear_invalid] DELETED {len(to_delete)} invalid proxies", flush=True)
    else:
        print("[clear_invalid] no invalid proxies found", flush=True)
    print(f"[clear_invalid] remaining in {KEY}: {r.hlen(KEY)}", flush=True)


if __name__ == "__main__":
    main()
