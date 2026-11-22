#!/usr/bin/env python3
"""Chạy MỘT lần thí nghiệm CoAP trên topology của Gia Bảo (topo.py), cần root:

  sudo python3 run_coap_mininet.py -n 20 --policy con --phases 60:5 --out out/k2_con_p5_r1
  sudo python3 run_coap_mininet.py -n 20 --policy adaptive --phases 60:1 60:15 60:1 --out out/k7_adaptive

Sơ đồ: h1..hN -> s1 -> hg (gateway, chạy coap_adapter) -> r1 -> server (chạy coap_server).
Liên kết WAN là hg-eth1 <-> r1-eth0; netem đặt ở đây (cả 2 đầu nếu --loss-dir both).
Mất gói mỗi chiều = p, nên mất gói khứ hồi của CON = 1-(1-p)^2. Chốt với Bảo xem wan.py
đặt mất gói một chiều hay hai chiều và chỉnh --delay-ms, --rate-mbit cho khớp.

Đầu ra trong --out: server_coap.csv, adapter_coap.csv(+.events.csv, .summary.json),
phases.csv, qdisc_*.txt, gw_wan.pcap (nếu --pcap), *.out
"""
import argparse
import csv
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SERVER_IP, GW_IP = "10.0.3.2", "10.0.1.1"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--sensors", type=int, default=20, help="số cảm biến (topo.py yêu cầu 10..100)")
    ap.add_argument("--policy", choices=["non", "con", "adaptive", "adaptive_batch"], default="non")
    ap.add_argument("--k", type=int, default=1, help="cỡ lô cố định cho non/con (K5)")
    ap.add_argument("--phases", nargs="+", default=["60:1"], help="giây:%%mất_gói, ví dụ 60:1 60:15 60:1")
    ap.add_argument("--delay-ms", type=float, default=20)
    ap.add_argument("--rate-mbit", type=float, default=0, help="0 = không giới hạn băng thông")
    ap.add_argument("--loss-dir", choices=["both", "fwd"], default="both")
    ap.add_argument("--interval", type=float, default=1.0, help="chu kỳ gửi của mỗi cảm biến (s)")
    ap.add_argument("--jitter", action="store_true", help="lệch pha ngẫu nhiên giữa các cảm biến (sensor.py --jitter)")
    ap.add_argument("--adapter-args", default="", help="tham số thêm cho coap_adapter.py")
    ap.add_argument("--pcap", action="store_true", help="bắt pcap trên hg-eth1")
    ap.add_argument("--cli", action="store_true", help="mở CLI Mininet sau khi chạy xong")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from mininet.net import Mininet
    from mininet.log import setLogLevel
    from topo import IoTWanTopo

    phases = [(float(p.split(":")[0]), p.split(":")[1]) for p in a.phases]
    total = sum(d for d, _ in phases)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    py = "python3"

    setLogLevel("warning")
    net = Mininet(topo=IoTWanTopo(n_sensors=a.sensors), controller=None, autoSetMacs=True)
    net.start()
    try:
        hg, r1, server = net.get("hg"), net.get("r1"), net.get("server")
        hg.cmd("ip route add 10.0.3.0/24 via 10.0.2.2")
        r1.cmd("ip route add 10.0.1.0/24 via 10.0.2.1")

        def netem(loss):
            base = f"netem delay {a.delay_ms}ms loss {loss}%"
            if a.rate_mbit:
                base += f" rate {a.rate_mbit}mbit"
            hg.cmd(f"tc qdisc replace dev hg-eth1 root {base}")
            if a.loss_dir == "both":
                r1.cmd(f"tc qdisc replace dev r1-eth0 root {base}")

        def bg(node, cmd, name):
            node.cmd(f"{cmd} & echo $! > {out}/{name}.pid")

        def stop(node, name, sig="INT"):
            node.cmd(f"kill -{sig} $(cat {out}/{name}.pid) 2>/dev/null")

        netem(phases[0][1])
        r = hg.cmd(f"ping -c 2 -W 2 {SERVER_IP}")
        if " 0 received" in r or "100% packet loss" in r:
            sys.exit("hg không ping được server - kiểm tra topology/route:\n" + r)

        bg(server, f"{py} {HERE}/coap_server.py --port 5683 --log {out}/server_coap.csv > {out}/server.out 2>&1", "server")
        if a.pcap:
            bg(hg, f"tcpdump -i hg-eth1 -U -w {out}/gw_wan.pcap udp port 5683 > /dev/null 2>&1", "tcpdump")
        time.sleep(1)
        bg(hg, f"{py} {HERE}/coap_adapter.py --listen 0.0.0.0:5000 --server {SERVER_IP}:5683 "
               f"--policy {a.policy} --k {a.k} --duration {total + 3} --drain 10 "
               f"--log {out}/adapter_coap.csv {a.adapter_args} > {out}/adapter.out 2>&1", "adapter")
        time.sleep(1)

        # --- cảm biến + các pha mạng ---
        t0 = time.time()
        netem(phases[0][1])
        import sensor                      # sensor.py của Lâm, để cùng thư mục
        sens = sensor.start_sensors(net, a.sensors, gateway=GW_IP, port=5000, interval=a.interval,
                                    duration=total, log_dir=f"{out}/sensors", jitter=a.jitter)
        with open(f"{out}/phases.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["phase", "loss_pct", "t_start", "t_end"])
            for idx, (dur, loss) in enumerate(phases, 1):
                netem(loss)
                ts = time.time()
                print(f"[run] pha {idx}: mất gói {loss}% trong {dur:.0f}s", flush=True)
                time.sleep(dur)
                w.writerow([idx, loss, f"{ts:.3f}", f"{time.time():.3f}"])
                f.flush()

        time.sleep(15)      # chờ adapter xả lô và ACK tồn đọng rồi tự dừng
        sensor.stop_sensors(sens)
        stop(server, "server")
        if a.pcap:
            stop(hg, "tcpdump")
        time.sleep(1)
        open(f"{out}/qdisc_hg.txt", "w").write(hg.cmd("tc -s qdisc show dev hg-eth1"))
        open(f"{out}/qdisc_r1.txt", "w").write(r1.cmd("tc -s qdisc show dev r1-eth0"))
        print(f"[run] xong sau {time.time() - t0:.0f}s, log ở {out}", flush=True)
        if a.cli:
            from mininet.cli import CLI
            CLI(net)
    finally:
        net.stop()

    subprocess.run([sys.executable, f"{HERE}/quick_stats.py", f"{out}/adapter_coap.csv",
                    f"{out}/server_coap.csv", "--window", "10", "--sensors-dir", f"{out}/sensors"])


if __name__ == "__main__":
    main()
