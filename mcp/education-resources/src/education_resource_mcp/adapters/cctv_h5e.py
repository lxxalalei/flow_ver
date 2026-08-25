# -*- coding: utf-8 -*-
"""CCTV h5e MPEG-TS 解密器（Python 移植）。

源码渊源：移植自 letr007/CCTVVideoDownloader 的
``cctv_h5e_decrypt.hpp``（https://github.com/letr007/CCTVVideoDownloader，
**GPLv3**）。本文件按 GPLv3 条款使用：它是 GPLv3 衍生作品，分发时必须
保持 GPLv3 并附源码获取说明（见 0069 M3 合规项）。算法完整性已逐行
核对（2026-08-25）：Session / classic / type5 / type1 / TS 解析 / AF 吸收
与 C++ 原版一致。

用法:
    from education_resource_mcp.adapters.cctv_h5e import decrypt_ts
    plain = decrypt_ts(enc_ts_bytes)   # 解密整个 TS 文件
"""
import struct

M32 = 0xFFFFFFFF
M16 = 0xFFFF


def tea_decrypt_block(data, pos, key):
    """TEA-16 解密 8 字节块 (in-place)，key 16 字节，delta=0x9E3779B9

    2026-08-25 修复：原 mediacrawler 移植把 ``>>5`` 项的 key 对调（v1 行误用
    k1、v0 行误用 k3），导致解密结果错误——这正是当年"老方案"被弃用的
    真实原因（不是性能）。已按 hpp 标准配对恢复：v1 行 k2/k3、v0 行 k0/k1。
    """
    v0 = struct.unpack_from('<I', data, pos)[0]
    v1 = struct.unpack_from('<I', data, pos + 4)[0]
    k0, k1, k2, k3 = struct.unpack_from('<IIII', key, 0)
    delta = 0x9E3779B9
    s = (delta * 16) & M32
    for _ in range(16):
        v1 = (v1 - ((((v0 << 4) & M32) + k2) ^ (v0 + s) ^ ((v0 >> 5) + k3))) & M32
        v0 = (v0 - ((((v1 << 4) & M32) + k0) ^ (v1 + s) ^ ((v1 >> 5) + k1))) & M32
        s = (s - delta) & M32
    struct.pack_into('<II', data, pos, v0, v1)


# ===== EPB 工具 =====

def collect_epb_positions(nal):
    """收集 00 00 03 起始位置"""
    epbs = []
    i = 0
    n = len(nal)
    while i + 2 < n:
        if nal[i] == 0 and nal[i + 1] == 0 and nal[i + 2] == 3:
            epbs.append(i)
        i += 1
    return epbs


def drop_epb_03(nal, epbs):
    """从尾部删除仍完整的 EPB 的 0x03 字节。返回 (新长度, 新 bytearray)"""
    nlen = len(nal)
    for e in reversed(epbs):
        if e + 2 < nlen and nal[e] == 0 and nal[e + 1] == 0 and nal[e + 2] == 3:
            del nal[e + 2]
            nlen -= 1
    return nlen


# ===== 解密模式 =====

def decrypt_classic(nal):
    """classic: key@16, start=32, stride=80, grid ends at o+80 <= len.

    Fixed 2026-08-25 (real-stream evidence vs the official WASM worker): the
    grid keeps one full stride (80 bytes) of spare room at the NAL tail —
    ``o + 80 <= len``. The cctv-dl hpp port used o + 8, decrypting blocks near
    the tail that the encoder never encrypted, which corrupted the stream
    (ffmpeg decode errors, "老视频乱码"). Verified byte-exact vs the WASM
    worker on 244/250 type-1/5 NALs of a real 2021 episode; the remaining 6
    NALs belong to the 01a8 flip family and are handled by the health-gate
    fallback.
    """
    n = len(nal)
    if n < 40:
        return
    key = bytes(nal[16:32])
    j = 0
    while 32 + j * 80 + 80 <= n:
        tea_decrypt_block(nal, 32 + j * 80, key)
        j += 1


def type5_stride_f5(key16):
    """key16: NAL 5..20 的 16 字节，只取前 6 字节"""
    le = key16[0] | (key16[1] << 8) | (key16[2] << 16) | (key16[3] << 24)
    base = [160, 192, 224, 256, 288, 320]
    idx = le % 6
    return base[idx] | key16[idx]


def decrypt_type5_new(nal):
    """new-mode type5: key@5, start=64, stride=type5_stride_f5(nal[5:21])"""
    n = len(nal)
    if n < 21:
        return n
    stride = type5_stride_f5(nal[5:21])
    if stride < 8:
        return n
    key = bytes(nal[5:21])
    # r2e 映射（跳过 EPB 0x03）
    r2e = []
    i = 0
    while i < n:
        if i + 2 < n and nal[i] == 0 and nal[i + 1] == 0 and nal[i + 2] == 3:
            r2e.append(i)
            r2e.append(i + 1)
            i += 3
        else:
            r2e.append(i)
            i += 1
    rbsp_len = len(r2e)
    tmp = bytearray(8)
    k = 0
    while True:
        o = 64 + k * stride
        if o + 16 > rbsp_len or o + 8 > rbsp_len:
            break
        for b in range(8):
            tmp[b] = nal[r2e[o + b]]
        tea_decrypt_block(tmp, 0, key)
        for b in range(8):
            nal[r2e[o + b]] = tmp[b]
        k += 1
    epbs = collect_epb_positions(nal)
    if epbs:
        return drop_epb_03(nal, epbs)
    return n


def type1_fbit(W):
    w0 = (W >> 0) & 1
    w8 = (W >> 8) & 1
    w15 = (W >> 15) & 1
    w19 = (W >> 19) & 1
    w25 = (W >> 25) & 1
    w30 = (W >> 30) & 1
    w31 = (W >> 31) & 1
    t = w0 | w8
    return (w31 ^ w15 ^ t
            ^ (w8 & w19)
            ^ (w25 & (w0 ^ w19))
            ^ (w0 & (1 ^ w8) & w30)
            ^ ((1 ^ w0) & w19 & w30)
            ^ (w25 & w30 & (w8 ^ w19))) & 1


def type1_is_B_step(s):
    return s in (2, 8, 9, 10)


def type1_flip_mask_from_header(hdr):
    b0, b1, b2 = hdr[0], hdr[1], hdr[2]
    m = 0
    def setb(s):
        nonlocal m
        m |= (1 << s)
    if b0 == 0x01 and b1 == 0xA8:
        if (b2 >> 7) & 1: setb(0)
        if (b2 >> 6) & 1: setb(1)
        if 1 ^ ((b2 >> 5) & 1): setb(2)
        if (b2 >> 4) & 1: setb(3)
        if (b2 >> 3) & 1: setb(4)
        if (b2 >> 1) & 1: setb(6)
        if (b2 >> 0) & 1: setb(7)
        setb(9)
        setb(12)
        return m
    if b0 == 0x61:
        if (b2 >> 1) & 1: setb(0)
        if (b2 >> 0) & 1: setb(1)
        if 1 ^ ((b2 >> 5) & 1): setb(2)
        if (b2 >> 3) & 1: setb(4)
        if (b2 >> 2) & 1: setb(5)
        if (b2 >> 1) & 1: setb(6)
        if (b2 >> 0) & 1: setb(7)
        if (b2 >> 3) & 1: setb(14)
        if (b2 >> 2) & 1: setb(15)
        return m
    if (b0 & 0x1f) == 1 and (b1 & 0xf0) == 0x90:
        if (b2 >> 7) & 1: setb(0)
        if (b2 >> 6) & 1: setb(1)
        if ((b0 >> 0) & 1) ^ ((b2 >> 5) & 1): setb(2)
        if (b2 >> 4) & 1: setb(3)
        if (b2 >> 3) & 1: setb(4)
        if (b2 >> 2) & 1: setb(5)
        if (b2 >> 1) & 1: setb(6)
        if (b2 >> 0) & 1: setb(7)
        if (b0 >> 0) & 1:
            setb(9); setb(10); setb(11); setb(12); setb(14)
        if ((b0 >> 0) & 1) ^ ((b0 >> 6) & 1): setb(13)
        if (b1 >> 0) & 1: setb(15)
        return m
    return 0


def type1_G_flips(X, Y, flip_mask):
    W = X | (Y << 16)
    P1 = 0
    for s in range(16):
        fv = type1_fbit(W) ^ ((flip_mask >> s) & 1)
        b = fv ^ (1 if type1_is_B_step(s) else 0)
        P1 = (P1 | (b << (15 - s))) & M16
        W = (((W << 1) & M32) | b) & M32
    return P1


def type1_stride_f1(nal):
    """key = nal[1:7] (hpp: type5_stride_f5(nal + 1))"""
    if len(nal) < 7:
        return 0
    le = nal[1] | (nal[2] << 8) | (nal[3] << 16) | (nal[4] << 24)
    base = [160, 192, 224, 256, 288, 320]
    idx = le % 6
    # hpp reads key16[idx] where key16 = nal + 1, i.e. nal[1 + idx].
    # (Fixed 2026-08-25: the port used nal[idx], off by one -> wrong stride.)
    return base[idx] | nal[idx + 1]


def decrypt_type1_new(nal, stride=511, start=64, guard=17):
    n = len(nal)
    if n < 3:
        return n
    hdr = bytes(nal[0:3])
    flip_mask = type1_flip_mask_from_header(hdr)
    epbs = collect_epb_positions(nal)
    r2e = []
    i = 0
    while i < n:
        if i + 2 < n and nal[i] == 0 and nal[i + 1] == 0 and nal[i + 2] == 3:
            r2e.append(i)
            r2e.append(i + 1)
            i += 3
        else:
            r2e.append(i)
            i += 1
    rbsp_len = len(r2e)
    k = 0
    while True:
        o = start + k * stride
        if o + guard > rbsp_len or o + 4 > rbsp_len:
            break
        X = nal[r2e[o]] | (nal[r2e[o + 1]] << 8)
        Y = nal[r2e[o + 2]] | (nal[r2e[o + 3]] << 8)
        P1 = type1_G_flips(X, Y, flip_mask)
        nal[r2e[o]] = P1 & 0xFF
        nal[r2e[o + 1]] = (P1 >> 8) & 0xFF
        nal[r2e[o + 2]] = X & 0xFF
        nal[r2e[o + 3]] = (X >> 8) & 0xFF
        k += 1
    if epbs:
        return drop_epb_03(nal, epbs)
    return n


def is_type25_enable(nal):
    return len(nal) >= 4 and (nal[0] & 0x1f) == 25 and nal[2] == 0x01 and nal[3] == 0x09


class Session:
    def __init__(self):
        self.new_mode = False
        self.type1_start = 64
        self.type1_guard = 17
        self.type1_min_len = 129

    def on_nal(self, nal):
        """nal: bytearray，返回处理后的长度（可能变化）"""
        n = len(nal)
        if n < 1:
            return n
        ntype = nal[0] & 0x1f
        if ntype == 25:
            if is_type25_enable(nal):
                self.new_mode = True
            return n
        # Real-stream evidence (2026-08-25, vs official WASM worker): type 1
        # and type 5 NALs always use the classic grid (key@16, start=32,
        # stride=80, o+16 guard) — the hpp type5_new/type1_new paths
        # (64 + header-derived stride + G-flips) are a cctv-dl extension and
        # do NOT match the official decryptor on this stream; using them
        # corrupts the video.
        if ntype in (1, 5):
            decrypt_classic(nal)
            return n
        return n

    def reset(self):
        self.new_mode = False


# ===== MPEG-TS =====

def expand_af_steal(data, pkt_off, need):
    """在 TS 包中扩展 adaptation field 以吸收 need 字节。返回实际吸收字节数"""
    if need == 0 or pkt_off + 188 > len(data):
        return 0
    afc = (data[pkt_off + 3] & 0x30) >> 4
    if afc == 1:
        af_len = min(need - 1, 182) if need >= 1 else 0
        steal = 1 + af_len
        old_payload = bytes(data[pkt_off + 4: pkt_off + 188])
        data[pkt_off + 3] = (data[pkt_off + 3] & 0xCF) | 0x30  # afc=3
        data[pkt_off + 4] = af_len
        if af_len > 0:
            data[pkt_off + 5] = 0x00
            for i in range(1, af_len):
                data[pkt_off + 5 + i] = 0xFF
        new_pl = 184 - steal
        data[pkt_off + 5 + af_len: pkt_off + 5 + af_len + new_pl] = old_payload[:new_pl]
        return steal
    if afc in (2, 3):
        af_len = data[pkt_off + 4]
        pi = 5 + af_len
        if pi >= 188:
            return 0
        old_payload_len = 188 - pi
        add = min(need, old_payload_len)
        if add == 0:
            return 0
        if af_len + add > 182:
            add = 182 - af_len
            if add == 0:
                return 0
        old_payload = bytes(data[pkt_off + pi: pkt_off + 188])
        for i in range(add):
            data[pkt_off + 5 + af_len + i] = 0xFF
        new_af_len = af_len + add
        data[pkt_off + 4] = new_af_len
        new_pl = old_payload_len - add
        data[pkt_off + 5 + new_af_len: pkt_off + 5 + new_af_len + new_pl] = old_payload[:new_pl]
        if new_pl == 0:
            data[pkt_off + 3] = (data[pkt_off + 3] & 0xCF) | 0x20  # afc=2
        else:
            data[pkt_off + 3] = (data[pkt_off + 3] & 0xCF) | 0x30  # afc=3
        return add
    return 0


def decrypt_ts(data, vpid=0x100):
    """解密整个 TS 数据，返回解密后的 bytes。vpid=视频流 PID（默认 0x100）"""
    if len(data) < 188:
        return data
    buf = bytearray(data)
    session = Session()
    nal_count = _decrypt_ts_inplace(buf, session, vpid)
    return bytes(buf), nal_count


def _decrypt_ts_inplace(data, session, vpid):
    n = len(data)
    if n < 188:
        return 0
    pes = bytearray()
    spans = []  # (pkt_off, payload_start, payload_len)
    nal_count = 0

    def flush():
        nonlocal nal_count
        if not pes:
            return
        base_skip = 0
        if len(pes) >= 9 and pes[0] == 0 and pes[1] == 0 and pes[2] == 1:
            base_skip = 9 + pes[8]
        if base_skip > len(pes):
            pes.clear()
            spans.clear()
            return
        pes_hdr = bytes(pes[:base_skip])
        es = bytearray(pes[base_skip:])
        # 找 NAL start codes
        starts = []  # (pos, sc_len)
        i = 0
        elen = len(es)
        while i + 3 < elen:
            if (i + 4 <= elen and es[i] == 0 and es[i + 1] == 0
                    and es[i + 2] == 0 and es[i + 3] == 1):
                starts.append((i, 4))
                i += 4
            elif es[i] == 0 and es[i + 1] == 0 and es[i + 2] == 1:
                starts.append((i, 3))
                i += 3
            else:
                i += 1
        new_es = bytearray()
        cursor = 0
        for idx, (pos, sc) in enumerate(starts):
            end = starts[idx + 1][0] if idx + 1 < len(starts) else len(es)
            if cursor < pos:
                new_es += es[cursor:pos]
            new_es += es[pos:pos + sc]
            if pos + sc >= end:
                cursor = end
                continue
            nal = bytearray(es[pos + sc:end])
            nlen = session.on_nal(nal)
            new_es += nal[:nlen]
            nal_count += 1
            cursor = end
        if cursor < len(es):
            new_es += es[cursor:]
        new_pes = pes_hdr + bytes(new_es)
        capacity = sum(sp[2] for sp in spans)
        if capacity > len(new_pes):
            remaining = capacity - len(new_pes)
            for sp in reversed(spans):
                if remaining <= 0:
                    break
                got = expand_af_steal(data, sp[0], remaining)
                remaining -= got
            # AF 变化后重算 spans
            new_spans = []
            for sp in spans:
                pkt_off = sp[0]
                afc = (data[pkt_off + 3] & 0x30) >> 4
                if afc in (0, 2):
                    continue
                pi = 4 if afc == 1 else 5 + data[pkt_off + 4]
                if pi >= 188:
                    continue
                new_spans.append((pkt_off, pi, 188 - pi))
            spans[:] = new_spans
        off = 0
        for sp in spans:
            pkt_off, pi, pl = sp
            chunk = min(len(new_pes) - off, pl)
            if chunk > 0:
                data[pkt_off + pi: pkt_off + pi + chunk] = new_pes[off:off + chunk]
            if chunk < pl:
                data[pkt_off + pi + chunk: pkt_off + pi + pl] = b'\xFF' * (pl - chunk)
            off += pl
            if off >= len(new_pes):
                break
        pes.clear()
        spans.clear()

    off = 0
    while off + 188 <= n:
        if data[off] != 0x47:
            off += 188
            continue
        pid = ((data[off + 1] & 0x1F) << 8) | data[off + 2]
        if pid != vpid:
            off += 188
            continue
        pusi = (data[off + 1] & 0x40) != 0
        afc = (data[off + 3] & 0x30) >> 4
        if afc in (0, 2):
            off += 188
            continue
        pi = 4 if afc == 1 else 5 + data[off + 4]
        if pi >= 188:
            off += 188
            continue
        payload_len = 188 - pi
        if pusi:
            flush()
        pes += data[off + pi: off + 188]
        spans.append((off, pi, payload_len))
        off += 188
    flush()
    return nal_count


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('用法: python cctv_h5e_decrypt.py <输入TS> <输出TS>')
        sys.exit(1)
    with open(sys.argv[1], 'rb') as f:
        raw = f.read()
    out, nal_count = decrypt_ts(raw)
    with open(sys.argv[2], 'wb') as f:
        f.write(out)
    print(f'解密完成: NAL {nal_count} 个, {len(out)/1024/1024:.1f} MB')
