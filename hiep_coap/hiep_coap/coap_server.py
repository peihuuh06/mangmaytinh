#!/usr/bin/env python3
"""CoAP server ghi log (việc của Hiệp, hạn 24/11).

Nhận POST /s chứa 1 hoặc nhiều bản ghi 10 byte (xem RECORD). CON -> trả ACK 2.04
(piggybacked); NON -> không trả lời. CON bị gửi lại (cùng Message ID) chỉ ghi log
một lần, ACK được gửi lại để gateway thôi truyền lại (RFC 7252 mục 4.5).

Log CSV (mỗi dòng = một số đo):
  recv_ts, sid, seq, mtype, batch, dgram_bytes, src_port
"""
import argparse
import asyncio
import csv
import json
import signal
import struct
import time

import coap_lite as c

# Khuôn một số đo 10 byte: sensor_id (2) + seq (4) + value float32 (4).
# !!! Đối chiếu với sensor.py của Lâm; nếu khác thì chỉ cần sửa dòng này.
RECORD = struct.Struct("!HIf")

EXCHANGE_LIFETIME = 247.0


class CoapServer(asyncio.DatagramProtocol):
    def __init__(self, logfile, path):
        self.path = path
        self.f = open(logfile, "w", newline="", buffering=1)
        self.w = csv.writer(self.f)
        self.w.writerow(["recv_ts", "sid", "seq", "mtype", "batch", "dgram_bytes", "src_port"])
        self.seen = {}          # (addr, mid) -> (thời điểm, ACK đã gửi)
        self.stats = dict(msgs_con=0, msgs_non=0, dup_con=0, records=0,
                          rx_bytes=0, tx_bytes=0, bad=0)

    def connection_made(self, transport):
        self.transport = transport

    def _send(self, pkt, addr):
        self.stats["tx_bytes"] += len(pkt)
        self.transport.sendto(pkt, addr)

    def datagram_received(self, data, addr):
        t = time.time()
        try:
            m = c.decode(data)
        except ValueError:
            self.stats["bad"] += 1
            return
        if m.type in (c.ACK, c.RST):
            return
        self.stats["rx_bytes"] += len(data)
        if m.type == c.CON and m.code == c.EMPTY:           # CoAP ping
            self._send(c.encode(c.RST, c.EMPTY, m.mid), addr)
            return
        key = (addr, m.mid)
        if m.type == c.CON:
            hit = self.seen.get(key)
            if hit:
                self.stats["dup_con"] += 1
                self._send(hit[1], addr)
                return
        if m.code != c.POST or c.uri_path(m) != [self.path]:
            if m.type == c.CON:
                self._send(c.encode(c.ACK, c.NOT_FOUND, m.mid, m.token), addr)
            return
        n, rem = divmod(len(m.payload), RECORD.size)
        if rem or n == 0:
            self.stats["bad"] += 1
            if m.type == c.CON:
                self._send(c.encode(c.ACK, c.BAD_REQUEST, m.mid, m.token), addr)
            return
        name = c.TYPE_NAME[m.type]
        self.stats["msgs_con" if m.type == c.CON else "msgs_non"] += 1
        self.stats["records"] += n
        for i in range(n):
            sid, seq, _ = RECORD.unpack_from(m.payload, i * RECORD.size)
            self.w.writerow([f"{t:.6f}", sid, seq, name, n, len(data), addr[1]])
        if m.type == c.CON:
            ack = c.encode(c.ACK, c.CHANGED, m.mid, m.token)
            self.seen[key] = (t, ack)
            if len(self.seen) % 1000 == 0:
                self.seen = {k: v for k, v in self.seen.items() if t - v[0] < EXCHANGE_LIFETIME}
            self._send(ack, addr)

    def close(self, summary_path):
        self.f.close()
        with open(summary_path, "w") as fh:
            json.dump(self.stats, fh, indent=2)


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5683)
    ap.add_argument("--path", default="s", help="Uri-Path của resource (mặc định: s)")
    ap.add_argument("--log", default="server_coap.csv")
    args = ap.parse_args()

    loop = asyncio.get_running_loop()
    proto = CoapServer(args.log, args.path)
    transport, _ = await loop.create_datagram_endpoint(lambda: proto, local_addr=(args.host, args.port))
    stop = asyncio.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, stop.set)
    print(f"[coap_server] lắng nghe udp://{args.host}:{args.port}/{args.path}  log={args.log}", flush=True)
    await stop.wait()
    transport.close()
    proto.close(args.log + ".summary.json")
    print("[coap_server] dừng:", proto.stats, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
