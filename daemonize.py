#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 proxyPool 的子命令变成真正的后台守护进程（macOS 没有 setsid，这里用双 fork 实现）。

用法:
    ./.venv/bin/python daemonize.py schedule
    ./.venv/bin/python daemonize.py server
    ./.venv/bin/python daemonize.py stop schedule
    ./.venv/bin/python daemonize.py status

日志写到 log/<name>.out，PID 写到 log/<name>.pid
"""
import os
import signal
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "log")
PYTHON = os.path.join(BASE, ".venv", "bin", "python")


def pid_file(name):
    return os.path.join(LOG_DIR, "%s.pid" % name)


def read_pid(name):
    try:
        with open(pid_file(name)) as f:
            return int(f.read().strip())
    except Exception:
        return None


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(name):
    if alive(read_pid(name)):
        print("%s 已在运行，PID=%s" % (name, read_pid(name)))
        return 1

    os.makedirs(LOG_DIR, exist_ok=True)
    out = os.path.join(LOG_DIR, "%s.out" % name)

    pid = os.fork()
    if pid > 0:
        # 父进程：等子进程把 PID 文件写出来
        for _ in range(50):
            if read_pid(name):
                break
            time.sleep(0.1)
        print("%s 已启动，PID=%s，日志: %s" % (name, read_pid(name), out))
        return 0

    # 第一层子进程：脱离会话
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    # 第二层子进程：真正的守护进程
    os.chdir(BASE)
    sys.stdout.flush()
    sys.stderr.flush()

    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    devnull = os.open(os.devnull, os.O_RDONLY)

    os.dup2(devnull, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    os.close(devnull)

    # 清掉本机透明代理，否则 requests 会走系统代理
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)

    with open(pid_file(name), "w") as f:
        f.write(str(os.getpid()))

    os.execv(PYTHON, [PYTHON, os.path.join(BASE, "proxyPool.py"), name])


def stop(name):
    pid = read_pid(name)
    if not alive(pid):
        print("%s 未在运行" % name)
        return 1
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.1)
    if alive(pid):
        os.kill(pid, signal.SIGKILL)
        print("%s 已强制结束 (PID=%s)" % (name, pid))
    else:
        print("%s 已停止 (PID=%s)" % (name, pid))
    try:
        os.remove(pid_file(name))
    except OSError:
        pass
    return 0


def status(name):
    pid = read_pid(name)
    if alive(pid):
        print("%s: 运行中 (PID=%s)" % (name, pid))
    else:
        print("%s: 未运行" % name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "stop":
        sys.exit(stop(target))
    if cmd == "status":
        for n in (["schedule", "server"] if not target else [target]):
            status(n)
        sys.exit(0)
    if cmd in ("schedule", "server"):
        sys.exit(start(cmd))

    print("未知命令: %s" % cmd)
    sys.exit(2)
