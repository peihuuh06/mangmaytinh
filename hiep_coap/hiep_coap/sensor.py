#!/usr/bin/env python3
#Khuôn dạng bản tin (10 byte, big-endian / network order):
#    +-----------+-----------+-----------+
#    | sensor_id |    seq    |   value   |
#    |  uint16   |  uint32   |  float32  |
#    |  2 byte   |  4 byte   |  4 byte   |
#    +-----------+-----------+-----------+
#  - sensor_id: số hiệu cảm biến 
#  - seq      : số thứ tự bản tin, đếm từ 1 đến 60
#  - value    : giá trị đo mô phỏng (ngẫu nhiên quanh 25.0)


import argparse
import os
import random
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

GATEWAY_IP = "10.0.1.1"   # hg-eth0 trong BangIP
GATEWAY_PORT = 5000       # cổng UDP (t tự đặt do trong bảng Ip ko có)
INTERVAL = 1.0            # chu kỳ gửi: 1 giây
DURATION = 60.0           # thời gian chạy: 60 giây -> 60 bản tin (seq 1..60)
LOG_DIR = "logs"

MSG = struct.Struct("!HIf")
assert MSG.size == 10, "ban tin phai dai dung 10 byte"


def build_message(sensor_id, seq, value):
    """Đóng gói bản tin 10 byte."""
    return MSG.pack(sensor_id, seq & 0xFFFFFFFF, value)


def format_time(t_ns):
    """Epoch nano giây -> 'YYYY-MM-DD HH:MM:SS.ffffff' (giờ local)."""
    sec, ns = divmod(t_ns, 1_000_000_000)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sec)) + f".{ns // 1000:06d}"


def run_sensor(sensor_id, gateway=GATEWAY_IP, port=GATEWAY_PORT,
               interval=INTERVAL, duration=DURATION, log_dir=LOG_DIR,
               jitter=False, stop=None):
    """Chạy một cảm biến trong `duration` giây (mặc định 60), gửi đúng
    duration/interval bản tin với seq = 1..60. duration = 0 nghĩa là chạy
    vô hạn. Dừng sớm nếu `stop` (threading.Event) được set.
    Trả về số bản tin đã gửi."""
    stop = stop or threading.Event()
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"sensor_h{sensor_id}.csv")

    rng = random.Random(sensor_id)  # seed theo id để chạy lại cho kết quả lặp lại
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Tổng số bản tin = duration / interval (60 s / 1 s = 60); None = chạy vô hạn
    total = round(duration / interval) if duration > 0 else None
    sent = 0
    seq = 1  # seq đếm từ 1 đến total
    with sock, open(log_path, "w", buffering=1) as log:  # buffering=1: ghi từng dòng
        log.write("sensor_id,seq,send_epoch_ns,send_time,size_bytes\n")

        start = time.monotonic()
        # jitter: lệch pha ngẫu nhiên trong [0, interval) để N cảm biến không gửi đồng loạt
        next_tick = start + (rng.uniform(0, interval) if jitter else 0.0)
        end = start + duration if duration > 0 else None

        while total is None or seq <= total:
            # Chờ tới mốc gửi kế tiếp; mốc cộng dồn nên không bị trôi theo thời gian xử lý
            if stop.wait(max(0.0, next_tick - time.monotonic())):
                break

            msg = build_message(sensor_id, seq, rng.gauss(25.0, 2.0))
            t_ns = time.time_ns()  # thời điểm gửi
            try:
                sock.sendto(msg, (gateway, port))
            except OSError as e:
                print(f"[h{sensor_id}] loi gui seq={seq}: {e}", file=sys.stderr)
            else:
                log.write(f"{sensor_id},{seq},{t_ns},{format_time(t_ns)},{len(msg)}\n")
                sent += 1

            seq += 1
            next_tick += interval

        # Bản tin thứ 60 gửi ở giây 59; chờ nốt tới giây 60 để tổng thời gian chạy đúng 60 s
        if end is not None:
            stop.wait(max(0.0, end - time.monotonic()))
    return sent


# ---------------------------------------------------------------------------
# Chạy N cảm biến trong Mininet: mỗi hX một tiến trình sensor.py riêng,
# nằm trong network namespace của host đó nên gói tin đi qua đúng topology.
# ---------------------------------------------------------------------------
def start_sensors(net, n_sensors, gateway=GATEWAY_IP, port=GATEWAY_PORT,
                  interval=INTERVAL, duration=DURATION, log_dir=LOG_DIR, jitter=False):
    """Khởi động cảm biến h1..hN. Trả về danh sách (Popen, file_stderr)."""
    log_dir = os.path.abspath(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    script = os.path.abspath(__file__)

    procs = []
    for i in range(1, n_sensors + 1):
        cmd = [
            sys.executable, script,
            "--id", str(i),
            "--gateway", gateway,
            "--port", str(port),
            "--interval", str(interval),
            "--duration", str(duration),
            "--log-dir", log_dir,
        ]
        if jitter:
            cmd.append("--jitter")
        err = open(os.path.join(log_dir, f"sensor_h{i}.err"), "w")
        p = net.get(f"h{i}").popen(cmd, stdout=subprocess.DEVNULL, stderr=err)
        procs.append((p, err))
    return procs


def stop_sensors(procs):
    """Dừng các cảm biến (SIGTERM để chúng đóng file log gọn gàng)."""
    for p, _ in procs:
        if p.poll() is None:
            p.terminate()
    for p, err in procs:
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
        err.close()


def main():
    ap = argparse.ArgumentParser(description="Cam bien IoT ao: gui ban tin UDP 10 byte moi giay toi gateway")
    ap.add_argument("--id", type=int, required=True, help="So hieu cam bien (1..100), trung voi host hX")
    ap.add_argument("--gateway", default=GATEWAY_IP, help="IP gateway (mac dinh 10.0.1.1)")
    ap.add_argument("--port", type=int, default=GATEWAY_PORT, help="Cong UDP cua gateway (mac dinh 5000)")
    ap.add_argument("--interval", type=float, default=INTERVAL, help="Chu ky gui, giay (mac dinh 1.0)")
    ap.add_argument("--duration", type=float, default=DURATION, help="Thoi gian chay, giay (mac dinh 60 -> 60 ban tin, seq 1..60; 0 = chay den khi bi dung)")
    ap.add_argument("--log-dir", default=LOG_DIR, help="Thu muc ghi log (mac dinh ./logs)")
    ap.add_argument("--jitter", action="store_true", help="Lech pha ngau nhien luc bat dau, tranh gui dong loat")
    args = ap.parse_args()

    if not (1 <= args.id <= 100):
        ap.error("--id phai nam trong khoang 1..100")
    if args.interval <= 0:
        ap.error("--interval phai > 0")
    if args.duration < 0:
        ap.error("--duration phai >= 0")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    run_sensor(args.id, args.gateway, args.port, args.interval,
               args.duration, args.log_dir, args.jitter, stop)


if __name__ == "__main__":
    main()
