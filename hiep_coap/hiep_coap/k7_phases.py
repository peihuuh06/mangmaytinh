#!/usr/bin/env python3
"""Đổi điều kiện mạng 3 pha cho K7 (tốt - xấu - tốt) trong lúc thí nghiệm đang chạy.

  python3 k7_phases.py --phases 60:0 60:20 60:0 \
      --cmd "tc qdisc change dev wan-h1 root netem delay 20ms loss {loss}%" \
      --cmd "tc qdisc change dev wan-s1 root netem delay 20ms loss {loss}%" \
      --out k7_phases.csv

--phases  giây:%mất_gói cho từng pha. --cmd có thể lặp (mỗi đầu liên kết WAN một lệnh);
{loss} được thay bằng % mất gói. `tc ... change` ghi đè TOÀN BỘ tham số netem, nên phải
lặp lại delay/rate giống wan.py của Bảo. Nếu Mininet chạy trong tiến trình Python
khác, thay subprocess bằng host.cmd(...) tương ứng. Ghi phases.csv để đối chiếu K7.
"""
import argparse, csv, subprocess, time

ap = argparse.ArgumentParser()
ap.add_argument("--phases", nargs="+", default=["60:0", "60:20", "60:0"])
ap.add_argument("--cmd", action="append", required=True)
ap.add_argument("--out", default="k7_phases.csv")
a = ap.parse_args()

with open(a.out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["phase", "loss_pct", "t_start", "t_end"])
    for i, ph in enumerate(a.phases, 1):
        dur, loss = ph.split(":")
        for cmd in a.cmd:
            subprocess.run(cmd.format(loss=loss), shell=True, check=True)
        t0 = time.time()
        print(f"[k7] pha {i}: mất gói {loss}% trong {dur}s", flush=True)
        time.sleep(float(dur))
        w.writerow([i, loss, f"{t0:.3f}", f"{time.time():.3f}"])
        f.flush()
