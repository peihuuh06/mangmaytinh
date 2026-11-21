#!/usr/bin/env python3
"""Gateway-adapter CoAP + gateway thích ứng (việc của Hiệp: 24/11 và 2/12).

Luồng: cảm biến --UDP--> adapter (cổng --listen) --CoAP CON/NON--> coap_server.
Mỗi datagram từ cảm biến chứa 1 (hoặc vài) bản ghi 10 byte.

Chính sách (--policy):
  non             luôn NON
  con             luôn CON (truyền lại theo RFC 7252)
  adaptive        EWMA mất gói: tốt -> NON, xấu -> CON
  adaptive_batch  như adaptive, và khi xấu thì gom --k-bad số đo vào một bản tin
Gom lô cố định cho K5: --policy non|con --k 5 (xả lô sau tối đa --max-wait giây).

Ước lượng mất gói (EWMA): mỗi LẦN GỬI một bản tin CON là một mẫu: không có ACK trước
khi hết RTO -> mẫu 1 (mất), có ACK -> mẫu 0.  p = alpha*mẫu + (1-alpha)*p.
Đây là mất gói KHỨ HỒI (request hoặc ACK mất) = 1-(1-p_mỗi_chiều)^2.
NON không có ACK nên không đo được; ở trạng thái tốt cứ --probe-every bản tin thì
gửi một bản tin dạng CON làm "mẫu dò" (vẫn là dữ liệu thật, không tốn thêm bản tin).
Chuyển trạng thái có trễ (hysteresis): tốt->xấu khi p >= --hi, xấu->tốt khi p <= --lo,
và giữ tối thiểu --dwell giây giữa hai lần chuyển để không dao động.

Log:
  <log>            mỗi dòng một số đo: t_in,sid,seq,mid,mode,batch_n,t_tx,retx,t_ack,status
  <log>.events.csv mỗi mẫu EWMA: t,sample_lost,p_hat,state(good/bad),mode_next,k_next
  <log>.summary.json  bộ đếm bản tin/byte/truyền lại
"""
import argparse
import asyncio
import csv
import json
import random
import signal
import time

import coap_lite as c
from coap_server import RECORD

GOOD, BAD = "good", "bad"
UDP_IP_OVERHEAD = 28   # IPv4 20 + UDP 8


class Pending:
    __slots__ = ("mid", "pkt", "items", "t_tx", "retx", "rto", "timer")


class Adapter:
    def __init__(self, a):
        self.a = a
        self.loop = asyncio.get_running_loop()
        self.buf = []                      # [(bản ghi, t_in)]
        self.flush_timer = None
        self.pending = {}
        self.mid = random.randrange(0x10000)
        self.msg_count = 0
        self.p_hat = 0.0
        self.state = GOOD
        self.last_switch = float("-inf")
        self.adaptive = a.policy.startswith("adaptive")
        self.stats = dict(tx_msgs=0, tx_con=0, tx_non=0, retx=0, tx_bytes=0,
                          acks=0, rx_bytes=0, failed=0, records_in=0, unfinished=0)
        self.f = open(a.log, "w", newline="", buffering=1)
        self.w = csv.writer(self.f)
        self.w.writerow(["t_in", "sid", "seq", "mid", "mode", "batch_n", "t_tx", "retx", "t_ack", "status"])
        self.fe = open(a.log + ".events.csv", "w", newline="", buffering=1)
        self.we = csv.writer(self.fe)
        self.we.writerow(["t", "sample_lost", "p_hat", "state", "mode_next", "k_next"])

    # ---------- chính sách ----------
    def target_k(self):
        a = self.a
        if a.policy in ("non", "con"):
            return a.k
        if a.policy == "adaptive_batch" and self.state == BAD:
            return a.k_bad
        return 1

    def pick_mode(self):
        a = self.a
        self.msg_count += 1
        if a.policy == "non":
            return c.NON
        if a.policy == "con":
            return c.CON
        if self.state == BAD:
            return c.CON
        return c.CON if self.msg_count % a.probe_every == 0 else c.NON

    def on_sample(self, lost):
        a = self.a
        self.p_hat = a.alpha * (1.0 if lost else 0.0) + (1 - a.alpha) * self.p_hat
        now = time.monotonic()
        if self.adaptive and now - self.last_switch >= a.dwell:
            if self.state == GOOD and self.p_hat >= a.hi:
                self.state, self.last_switch = BAD, now
            elif self.state == BAD and self.p_hat <= a.lo:
                self.state, self.last_switch = GOOD, now
                self.flush_all()           # k giảm về 1: xả hết lô đang chờ
        self.we.writerow([f"{time.time():.6f}", int(lost), f"{self.p_hat:.4f}", self.state,
                          "CON" if self.state == BAD else "NON", self.target_k()])

    # ---------- nhận từ cảm biến ----------
    def on_sensor(self, data):
        t = time.time()
        n = len(data) // RECORD.size
        for i in range(n):
            self.buf.append((data[i * RECORD.size:(i + 1) * RECORD.size], t))
        self.stats["records_in"] += n
        self.drain_buf()

    def drain_buf(self):
        k = min(self.target_k(), 100)      # 100 x 10 B = 1000 B < 1024, không cần block-wise
        while len(self.buf) >= k:
            self.send_batch([self.buf.pop(0) for _ in range(k)])
        if self.buf and self.flush_timer is None:
            self.flush_timer = self.loop.call_later(self.a.max_wait, self.flush_all)
        if not self.buf and self.flush_timer:
            self.flush_timer.cancel()
            self.flush_timer = None

    def flush_all(self):
        if self.flush_timer:
            self.flush_timer.cancel()
            self.flush_timer = None
        k = max(1, min(self.target_k(), 100))
        while self.buf:
            self.send_batch([self.buf.pop(0) for _ in range(min(k, len(self.buf)))])

    # ---------- gửi CoAP ----------
    def next_mid(self):
        while True:
            self.mid = (self.mid + 1) & 0xFFFF
            if self.mid not in self.pending:
                return self.mid

    def tx(self, pkt):
        self.coap.sendto(pkt)
        self.stats["tx_bytes"] += len(pkt)

    def send_batch(self, items):
        mode = self.pick_mode()
        mid = self.next_mid()
        pkt = c.encode(mode, c.POST, mid, b"", [(c.OPT_URI_PATH, self.a.path.encode())],
                       b"".join(r for r, _ in items))
        self.stats["tx_msgs"] += 1
        self.stats["tx_con" if mode == c.CON else "tx_non"] += 1
        t = time.time()
        self.tx(pkt)
        if mode == c.NON:
            self.log_rows(items, mid, "NON", t, 0, "", "sent")
            return
        p = Pending()
        p.mid, p.pkt, p.items, p.t_tx, p.retx = mid, pkt, items, t, 0
        p.rto = self.a.ack_timeout * random.uniform(1.0, c.ACK_RANDOM_FACTOR)
        p.timer = self.loop.call_later(p.rto, self.on_timeout, mid)
        self.pending[mid] = p

    def on_timeout(self, mid):
        p = self.pending.get(mid)
        if not p:
            return
        self.on_sample(True)
        if p.retx < self.a.max_retransmit:
            p.retx += 1
            p.rto *= 2
            self.stats["retx"] += 1
            self.tx(p.pkt)
            p.timer = self.loop.call_later(p.rto, self.on_timeout, mid)
        else:
            del self.pending[mid]
            self.stats["failed"] += 1
            self.log_rows(p.items, mid, "CON", p.t_tx, p.retx, "", "failed")

    def on_coap(self, data):
        self.stats["rx_bytes"] += len(data)
        try:
            m = c.decode(data)
        except ValueError:
            return
        if m.type != c.ACK:
            return
        p = self.pending.pop(m.mid, None)
        if not p:
            return                         # ACK trùng / đến muộn
        p.timer.cancel()
        self.stats["acks"] += 1
        self.on_sample(False)
        ok = (m.code >> 5) == 2
        self.log_rows(p.items, p.mid, "CON", p.t_tx, p.retx, f"{time.time():.6f}", "acked" if ok else "rejected")

    def log_rows(self, items, mid, mode, t_tx, retx, t_ack, status):
        for rec, t_in in items:
            try:
                sid, seq, _ = RECORD.unpack(rec)
            except Exception:
                sid = seq = ""
            self.w.writerow([f"{t_in:.6f}", sid, seq, mid, mode, len(items), f"{t_tx:.6f}", retx, t_ack, status])

    def finish(self):
        for p in list(self.pending.values()):
            p.timer.cancel()
            self.stats["unfinished"] += 1
            self.log_rows(p.items, p.mid, "CON", p.t_tx, p.retx, "", "pending")
        self.pending.clear()
        self.f.close()
        self.fe.close()
        s = dict(self.stats)
        s["tx_ip_bytes"] = s["tx_bytes"] + UDP_IP_OVERHEAD * (s["tx_msgs"] + s["retx"])
        s["rx_ip_bytes"] = s["rx_bytes"] + UDP_IP_OVERHEAD * s["acks"]
        s["policy"], s["final_state"], s["final_p_hat"] = self.a.policy, self.state, round(self.p_hat, 4)
        with open(self.a.log + ".summary.json", "w") as fh:
            json.dump(s, fh, indent=2)
        return s


class SensorProto(asyncio.DatagramProtocol):
    def __init__(self, ad):
        self.ad = ad

    def datagram_received(self, data, addr):
        self.ad.on_sensor(data)


class CoapProto(asyncio.DatagramProtocol):
    def __init__(self, ad):
        self.ad = ad

    def connection_made(self, transport):
        self.ad.coap = transport

    def datagram_received(self, data, addr):
        self.ad.on_coap(data)

    def error_received(self, exc):
        pass                               # ICMP unreachable: coi như mất gói


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", default="0.0.0.0:9000", help="nơi nhận số đo từ cảm biến (UDP)")
    ap.add_argument("--server", default="127.0.0.1:5683")
    ap.add_argument("--path", default="s")
    ap.add_argument("--policy", choices=["non", "con", "adaptive", "adaptive_batch"], default="non")
    ap.add_argument("--k", type=int, default=1, help="cỡ lô cố định cho non/con (K5: 1, 5, 20)")
    ap.add_argument("--k-bad", type=int, default=5, help="cỡ lô khi xấu (adaptive_batch)")
    ap.add_argument("--max-wait", type=float, default=1.0, help="xả lô sau tối đa giây này")
    ap.add_argument("--alpha", type=float, default=0.2)
    ap.add_argument("--hi", type=float, default=0.10)
    ap.add_argument("--lo", type=float, default=0.03)
    ap.add_argument("--dwell", type=float, default=10.0)
    ap.add_argument("--probe-every", type=int, default=5)
    ap.add_argument("--ack-timeout", type=float, default=c.ACK_TIMEOUT)
    ap.add_argument("--max-retransmit", type=int, default=c.MAX_RETRANSMIT)
    ap.add_argument("--duration", type=float, default=0, help="tự dừng sau n giây (0 = đến khi Ctrl-C)")
    ap.add_argument("--drain", type=float, default=10.0, help="chờ ACK tồn đọng tối đa n giây khi dừng")
    ap.add_argument("--log", default="adapter_coap.csv")
    a = ap.parse_args()

    loop = asyncio.get_running_loop()
    ad = Adapter(a)
    lh, lp = a.listen.rsplit(":", 1)
    sh, sp = a.server.rsplit(":", 1)
    stransport, _ = await loop.create_datagram_endpoint(lambda: SensorProto(ad), local_addr=(lh, int(lp)))
    await loop.create_datagram_endpoint(lambda: CoapProto(ad), remote_addr=(sh, int(sp)))
    stop = asyncio.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, stop.set)
    print(f"[adapter] policy={a.policy} {a.listen} -> coap://{a.server}/{a.path}", flush=True)
    try:
        await asyncio.wait_for(stop.wait(), a.duration or None)
    except asyncio.TimeoutError:
        pass
    stransport.close()
    ad.flush_all()
    end = time.monotonic() + a.drain
    while ad.pending and time.monotonic() < end:
        await asyncio.sleep(0.1)
    print("[adapter] dừng:", ad.finish(), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
