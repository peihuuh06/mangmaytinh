#!/usr/bin/env python3
"""Thống kê nhanh từ log adapter + log server (kiểm tra dữ liệu trước khi dùng analyze.py của Lâm).
Ghép theo (sid, seq). Trễ đầu-cuối = recv_ts (server) - thời điểm gửi (log cảm biến nếu có --sensors-dir, không thì t_in của adapter).
  python3 quick_stats.py adapter_coap.csv server_coap.csv [--window 10]
"""
import argparse, csv, statistics as st


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else float("nan")


def summarize(rows, recv):
    sent = len(rows)
    lat = [recv[k] - t for k, t in rows if k in recv]
    got = len(lat)
    return sent, got, (got / sent if sent else float("nan")), lat


ap = argparse.ArgumentParser()
ap.add_argument("adapter")
ap.add_argument("server")
ap.add_argument("--sensors-dir", default="", help="thư mục chứa sensor_h*.csv của Lâm: dùng làm số gói gửi và thời điểm gửi")
ap.add_argument("--window", type=float, default=0, help="chia theo cửa sổ n giây (K7)")
a = ap.parse_args()

recv = {}
for r in csv.DictReader(open(a.server)):
    recv.setdefault((r["sid"], r["seq"]), float(r["recv_ts"]))
rows = [((r["sid"], r["seq"]), float(r["t_in"])) for r in csv.DictReader(open(a.adapter))]
if a.sensors_dir:
    import glob
    rows = []
    for fn in glob.glob(f"{a.sensors_dir}/sensor_h*.csv"):
        for r in csv.DictReader(open(fn)):
            rows.append(((r["sensor_id"], r["seq"]), int(r["send_epoch_ns"]) / 1e9))
rows.sort(key=lambda x: x[1])
if not rows:
    raise SystemExit("log adapter rỗng")

sent, got, ratio, lat = summarize(rows, recv)
print(f"Tổng: gửi {sent}, tới {got}, tỉ lệ giao {ratio:.3f}")
if lat:
    print(f"Trễ (s): TB {st.mean(lat):.3f}  trung vị {st.median(lat):.3f}  p95 {pct(lat, .95):.3f}  max {max(lat):.3f}")
if a.window:
    t0 = rows[0][1]
    print(f"\n{'cửa sổ(s)':>10} {'gửi':>6} {'tới':>6} {'tỉ lệ':>6} {'trễ TB':>8} {'p95':>8}")
    i = 0
    while i * a.window <= rows[-1][1] - t0:
        w = [x for x in rows if i * a.window <= x[1] - t0 < (i + 1) * a.window]
        s, g, r, l = summarize(w, recv)
        if s:
            print(f"{i*a.window:>5.0f}-{(i+1)*a.window:<4.0f} {s:>6} {g:>6} {r:>6.2f} "
                  f"{(st.mean(l) if l else float('nan')):>8.3f} {pct(l,.95):>8.3f}")
        i += 1
