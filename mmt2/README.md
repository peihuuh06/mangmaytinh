# Phần việc của Trần Hữu Hiệp – CoAP và gateway thích ứng (Nhóm 11)

Chỉ dùng thư viện chuẩn Python 3 (không cần pip trong Mininet).

| File | Việc | Hạn |
|---|---|---|
| coap_lite.py | Mã hóa/giải mã CoAP (RFC 7252) | 24/11 |
| coap_server.py | CoAP server ghi log, ACK cho CON, chống trùng CON gửi lại | 24/11 |
| coap_adapter.py | Gateway-adapter CON/NON + gateway thích ứng (EWMA, NON/CON, gom lô) | 24/11, 2/12 |
| k7_phases.py | Đổi mạng 3 pha trong K7 | 6/12 |
| quick_stats.py | Thống kê nhanh tỉ lệ giao / trễ, theo cửa sổ thời gian | |
| fake_sensors.py, lossy_proxy.py | Chỉ để thử ngoài Mininet | |

## Điểm cần chốt với nhóm (giả định của mình)
1. Khuôn số đo 10 byte `!HIf` (sensor_id 2B, seq 4B, float32 4B) đã khớp sensor.py của Lâm.
2. Cảm biến (sensor.py của Lâm) gửi UDP tới gateway 10.0.1.1:5000; adapter nghe cổng 5000 mặc định.
3. Bốn chính sách K7 = `non`, `con`, `adaptive`, `adaptive_batch`. Hỏi Tuấn Anh để mô phỏng dùng đúng 4 chính sách này và cùng ngưỡng (alpha 0.2, hi 0.10, lo 0.03, dwell 10 s).
4. Tên cột log để Lâm viết analyze.py: server `recv_ts,sid,seq,mtype,batch,dgram_bytes,src_port`; adapter `t_in,sid,seq,mid,mode,batch_n,t_tx,retx,t_ack,status`. Trễ = recv_ts − t_in.

## Chạy tự động trên topology của Bảo (khuyên dùng)
topo.py để cùng thư mục, chạy bằng root:
```
sudo python3 run_coap_mininet.py -n 20 --policy con --phases 60:5 --out out/k2_con_p5_r1 --pcap
sudo python3 run_coap_mininet.py -n 20 --policy adaptive --phases 60:1 60:15 60:1 --out out/k7_adaptive
```
Script dựng topology, đặt netem trên hg-eth1 và r1-eth0, chạy server trên `server`, adapter trên `hg`,
cảm biến giả trên `h1` (chạy `sensor.start_sensors` của Lâm trên h1..hN), đổi pha mạng, rồi in thống kê.
Chưa thử trong Mininet thật. Nếu lỗi, `sudo mn -c` để dọn rồi gửi thông báo lỗi.
Lưu ý: interface của host Mininet nằm trong namespace riêng nên k7_phases.py (chạy ngoài namespace)
không đổi được netem; dùng run_coap_mininet.py thay thế.

## Cách chạy thủ công (trong Mininet CLI)
```
# server
python3 coap_server.py --port 5683 --log out/server_coap.csv
# gateway (chọn --policy)
python3 coap_adapter.py --server <IP_server>:5683 --policy con --duration 180 --log out/adapter_coap.csv
# cảm biến (sensor.py của Lâm) gửi tới gateway:5000
```
- K1: mạng tốt, `--policy non` rồi `--policy con`. topo.py của Bảo chỉ cho N từ 10 đến 100 nên không có N = 1.
- K2: mất gói 0/5/10/20 %, mỗi mức chạy `non` và `con` (nên 3 lần lặp để lấy trung bình).
- K5: `--policy non --k 5` / `--k 20` (và `con`), `--max-wait 1.0`.
- K7: mỗi chính sách một lần chạy 180 s. Song song chạy
  `python3 k7_phases.py --phases 60:0 60:20 60:0 --cmd "<tc ... netem ... loss {loss}%>" --out out/k7_phases.csv`
  (lệnh tc phải khớp wan.py của Bảo), rồi
  `python3 quick_stats.py out/adapter_coap.csv out/server_coap.csv --window 10`.
- Dừng: Ctrl-C hoặc `--duration`; adapter chờ ACK tồn đọng `--drain` giây rồi ghi `*.summary.json`.
- Đồ thị p̂(t) và trạng thái: `adapter_coap.csv.events.csv`.

## Đã thử
Ngoài Mininet bằng lossy_proxy (mất gói 0% → 20% mỗi chiều → 0%): gateway vào trạng thái xấu ngay khi mất gói bắt đầu, về tốt sau khi hết; không có số đo nào bị ghi trùng dù CON bị gửi lại. **Chưa chạy** trong Mininet/netem/Wireshark vì môi trường này không có.
