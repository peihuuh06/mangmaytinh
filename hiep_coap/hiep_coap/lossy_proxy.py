#!/usr/bin/env python3
"""Proxy UDP làm rớt gói - CHỈ để thử code khi chưa có Mininet/netem.
Mỗi chiều rớt với xác suất p; --phases "15:0 25:0.2 15:0" = (giây:p) lần lượt."""
import argparse, asyncio, random, time


class Proxy(asyncio.DatagramProtocol):
    def __init__(self, phases, server):
        self.phases, self.server, self.client, self.t0 = phases, server, None, time.monotonic()

    def p(self):
        t = time.monotonic() - self.t0
        for dur, p in self.phases:
            if t < dur:
                return p
            t -= dur
        return self.phases[-1][1]

    def connection_made(self, tr):
        self.tr = tr

    def datagram_received(self, data, addr):
        if random.random() < self.p():
            return
        if addr == self.server:
            if self.client:
                self.tr.sendto(data, self.client)
        else:
            self.client = addr
            self.tr.sendto(data, self.server)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=15684)
    ap.add_argument("--server", default="127.0.0.1:15683")
    ap.add_argument("--phases", default="1000:0")
    a = ap.parse_args()
    ph = [(float(x.split(":")[0]), float(x.split(":")[1])) for x in a.phases.split()]
    h, p = a.server.rsplit(":", 1)
    loop = asyncio.get_running_loop()
    # một socket cho phía client, một cho phía server
    cli = Proxy(ph, (h, int(p)))
    await loop.create_datagram_endpoint(lambda: cli, local_addr=("127.0.0.1", a.listen))
    await asyncio.sleep(10 ** 7)


asyncio.run(main())
