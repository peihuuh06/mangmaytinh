"""Mã hóa / giải mã bản tin CoAP (RFC 7252), chỉ dùng thư viện chuẩn của Python.

Lý do không dùng aiocoap: (1) trong Mininet không cần pip install, (2) kiểm soát
chính xác từng byte trên dây để đối chiếu với bảng byte kiểm chứng bằng Wireshark,
(3) tự cài đặt retransmission CON nên đo được số lần gửi lại và ước lượng mất gói.

Khuôn bản tin (RFC 7252, mục 3):
  byte 0 : Ver(2 bit)=1 | Type(2 bit) | TKL(4 bit)
  byte 1 : Code (class.detail)
  byte 2-3: Message ID
  Token (TKL byte), Options, 0xFF, Payload
"""
import struct
from collections import namedtuple

CON, NON, ACK, RST = 0, 1, 2, 3
TYPE_NAME = {CON: "CON", NON: "NON", ACK: "ACK", RST: "RST"}


def mk_code(cls, detail):
    return (cls << 5) | detail


EMPTY = mk_code(0, 0)
POST = mk_code(0, 2)
CHANGED = mk_code(2, 4)        # 2.04
BAD_REQUEST = mk_code(4, 0)    # 4.00
NOT_FOUND = mk_code(4, 4)      # 4.04

OPT_URI_PATH = 11

# RFC 7252 mục 4.8: tham số truyền lại của bản tin CON
ACK_TIMEOUT = 2.0
ACK_RANDOM_FACTOR = 1.5
MAX_RETRANSMIT = 4

Message = namedtuple("Message", "type code mid token options payload")


def _nibble(v):
    if v < 13:
        return v, b""
    if v < 269:
        return 13, bytes([v - 13])
    return 14, struct.pack("!H", v - 269)


def encode(mtype, code, mid, token=b"", options=(), payload=b""):
    """options: danh sách (số_option, bytes). Tự sắp xếp theo số option."""
    if len(token) > 8:
        raise ValueError("token dài tối đa 8 byte")
    out = bytearray(struct.pack("!BBH", (1 << 6) | (mtype << 4) | len(token), code, mid))
    out += token
    prev = 0
    for num, val in sorted(options, key=lambda o: o[0]):
        d_n, d_ext = _nibble(num - prev)
        l_n, l_ext = _nibble(len(val))
        out.append((d_n << 4) | l_n)
        out += d_ext + l_ext + val
        prev = num
    if payload:
        out.append(0xFF)
        out += payload
    return bytes(out)


def decode(data):
    if len(data) < 4:
        raise ValueError("bản tin quá ngắn")
    b0, code, mid = struct.unpack("!BBH", data[:4])
    if (b0 >> 6) != 1:
        raise ValueError("sai phiên bản")
    mtype, tkl = (b0 >> 4) & 3, b0 & 0x0F
    if tkl > 8:
        raise ValueError("TKL không hợp lệ")
    pos = 4
    token = data[pos:pos + tkl]
    pos += tkl
    options, num = [], 0
    try:
        while pos < len(data) and data[pos] != 0xFF:
            b = data[pos]
            pos += 1
            d, l = b >> 4, b & 0x0F
            if d == 13:
                d = data[pos] + 13
                pos += 1
            elif d == 14:
                d = struct.unpack("!H", data[pos:pos + 2])[0] + 269
                pos += 2
            elif d == 15:
                raise ValueError("option delta = 15")
            if l == 13:
                l = data[pos] + 13
                pos += 1
            elif l == 14:
                l = struct.unpack("!H", data[pos:pos + 2])[0] + 269
                pos += 2
            elif l == 15:
                raise ValueError("option length = 15")
            num += d
            options.append((num, data[pos:pos + l]))
            pos += l
    except (IndexError, struct.error):
        raise ValueError("option bị cắt cụt")
    payload = b""
    if pos < len(data):
        payload = data[pos + 1:]
        if not payload:
            raise ValueError("có payload marker nhưng payload rỗng")
    return Message(mtype, code, mid, token, options, payload)


def uri_path(msg):
    return [v.decode(errors="replace") for n, v in msg.options if n == OPT_URI_PATH]
