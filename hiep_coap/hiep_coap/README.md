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
1. Khuôn số đo 10 byte: `!HIf` (sensor_id 2B, seq 4B, float32 4B) – dòng `RECORD` trong coap_server.py. Đối chiếu sensor.py của Lâm.
2. Cảm biến gửi UDP tới adapter ở cổng 9000 (`--listen`). Nếu sensor.py gửi cách khác, sửa lớp SensorProto.
3. Bốn chính sách K7 = `non`, `con`, `adaptive`, `adaptive_batch`. Hỏi Tuấn Anh để mô phỏng dùng đúng 4 chính sách này và cùng ngưỡng (alpha 0.2, hi 0.10, lo 0.03, dwell 10 s).
4. Tên cột log để Lâm viết analyze.py: server `recv_ts,sid,seq,mtype,batch,dgram_bytes,src_port`; adapter `t_in,sid,seq,mid,mode,batch_n,t_tx,retx,t_ack,status`. Trễ = recv_ts − t_in.

## Cách chạy (trong Mininet; h_srv = server, h_gw = gateway)
```
# server
python3 coap_server.py --port 5683 --log out/server_coap.csv
# gateway (chọn --policy)
python3 coap_adapter.py --server <IP_server>:5683 --policy con --duration 180 --log out/adapter_coap.csv
# cảm biến (sensor.py của Lâm) gửi tới gateway:9000
```
- K1: mạng tốt, `--policy non` rồi `--policy con`, N = 1, 10, 50.
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
