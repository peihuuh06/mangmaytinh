#!/usr/bin/env python3
"""Cảm biến giả để thử code ngoài Mininet (khi chạy thật dùng sensor.py của Lâm)."""
import argparse, asyncio, random, socket, struct

from coap_server import RECORD


async def sensor(sock, dest, sid, interval, end, loop):
    await asyncio.sleep(sid * interval / max(1, sensor.n))
    seq = 0
    while loop.time() < end:
        sock.sendto(RECORD.pack(sid, seq, random.gauss(25, 2)), dest)
        seq += 1
        await asyncio.sleep(interval)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="127.0.0.1:9000")
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=60)
    a = ap.parse_args()
    h, p = a.dest.rsplit(":", 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    loop = asyncio.get_running_loop()
    sensor.n = a.n
    end = loop.time() + a.duration
    await asyncio.gather(*[sensor(sock, (h, int(p)), i, a.interval, end, loop) for i in range(a.n)])


asyncio.run(main())
