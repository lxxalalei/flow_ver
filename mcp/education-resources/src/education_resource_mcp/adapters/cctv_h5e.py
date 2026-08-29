# -*- coding: utf-8 -*-
"""CCTV H5E MPEG-TS decryptor.

This module keeps the repository's existing native Python implementation and
restores the protocol mode switch that is signalled by H.264 NAL type 25.
Before that marker, type 1/5 NALs use the classic TEA grid. After it, type 5
uses the dynamic TEA grid and type 1 uses the header-derived transform.

Historical provenance: this repository's native H5E implementation was derived
from letr007/CCTVVideoDownloader and is documented as GPLv3 in plan 0069. This
change only restructures the repository's existing implementation and restores
its protocol dispatch; it does not change that provenance.
"""
from __future__ import annotations

import struct

M32 = 0xFFFFFFFF
M16 = 0xFFFF
_TYPE_STRIDE_BASE = (160, 192, 224, 256, 288, 320)


def tea_decrypt_block(data: bytearray, pos: int, key: bytes) -> None:
    """Decrypt one 8-byte TEA-16 block in place."""
    v0 = struct.unpack_from("<I", data, pos)[0]
    v1 = struct.unpack_from("<I", data, pos + 4)[0]
    k0, k1, k2, k3 = struct.unpack_from("<IIII", key, 0)
    delta = 0x9E3779B9
    total = (delta * 16) & M32
    for _ in range(16):
        v1 = (
            v1
            - ((((v0 << 4) & M32) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))
        ) & M32
        v0 = (
            v0
            - ((((v1 << 4) & M32) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))
        ) & M32
        total = (total - delta) & M32
    struct.pack_into("<II", data, pos, v0, v1)


def collect_epb_positions(nal: bytearray) -> list[int]:
    """Return start offsets of H.264 emulation-prevention sequences 00 00 03."""
    return [
        index
        for index in range(max(0, len(nal) - 2))
        if nal[index] == 0 and nal[index + 1] == 0 and nal[index + 2] == 3
    ]


def _rbsp_to_ebsp_map(nal: bytearray) -> list[int]:
    """Map RBSP indexes to EBSP indexes while omitting EPB 0x03 bytes."""
    mapping: list[int] = []
    index = 0
    total = len(nal)
    while index < total:
        if (
            index + 2 < total
            and nal[index] == 0
            and nal[index + 1] == 0
            and nal[index + 2] == 3
        ):
            mapping.extend((index, index + 1))
            index += 3
        else:
            mapping.append(index)
            index += 1
    return mapping


def drop_epb_03(nal: bytearray, epbs: list[int]) -> int:
    """Drop still-present EPB 0x03 bytes and return the new NAL length."""
    length = len(nal)
    for start in reversed(epbs):
        if (
            start + 2 < length
            and nal[start] == 0
            and nal[start + 1] == 0
            and nal[start + 2] == 3
        ):
            del nal[start + 2]
            length -= 1
    return length


def decrypt_classic(nal: bytearray) -> int:
    """Classic H5E mode: key@16, data@32, stride 80 on the RBSP grid.

    Byte-level calibration against the official worker on real 2018/2021/2026
    streams shows classic mode shares the new-mode EPB discipline: emulation
    prevention is collected on the encrypted NAL, stride-80 TEA cells are
    decrypted over RBSP coordinates with ``key = RBSP[16:32]``, and the
    compacted RBSP is emitted. Decrypting on the raw EBSP grid desynced every
    cell after the first emulation-prevention sequence. NALs below the
    session-wide 129-byte threshold are left untouched, EPBs included; the
    official worker ships those still encrypted in both modes.
    """
    length = len(nal)
    if length < 40:
        return length
    epbs = collect_epb_positions(nal)
    mapping = _rbsp_to_ebsp_map(nal)
    rbsp_len = len(mapping)
    if rbsp_len < 112:
        return length

    key = bytes(nal[mapping[index]] for index in range(16, 32))
    block = bytearray(8)
    offset = 32
    while offset + 80 <= rbsp_len:
        for index in range(8):
            block[index] = nal[mapping[offset + index]]
        tea_decrypt_block(block, 0, key)
        for index in range(8):
            nal[mapping[offset + index]] = block[index]
        offset += 80

    return drop_epb_03(nal, epbs) if epbs else length


def type5_stride_f5(key16: bytes | bytearray) -> int:
    """Resolve the new-mode type-5 stride from the first six key bytes."""
    if len(key16) < 6:
        return 0
    little = (
        key16[0]
        | (key16[1] << 8)
        | (key16[2] << 16)
        | (key16[3] << 24)
    )
    index = little % len(_TYPE_STRIDE_BASE)
    return _TYPE_STRIDE_BASE[index] | key16[index]


def decrypt_type5_new(nal: bytearray) -> int:
    """Decrypt a type-5 NAL in the post-type25 H5E mode."""
    length = len(nal)
    if length < 21:
        return length
    key = bytes(nal[5:21])
    stride = type5_stride_f5(key)
    if stride < 8:
        return length

    # The RBSP grid is defined from the encoded NAL. Preserve the original
    # emulation-prevention positions before any decrypted bytes are written;
    # after the transform, only those original 00 00 03 sequences that still
    # exist are removed. Re-scanning the mutated NAL can invent/drop the wrong
    # EPB when a decrypted cell itself contains 00 00 03.
    epbs = collect_epb_positions(nal)
    mapping = _rbsp_to_ebsp_map(nal)
    rbsp_len = len(mapping)
    block = bytearray(8)
    offset = 64
    while offset + 16 <= rbsp_len:
        for index in range(8):
            block[index] = nal[mapping[offset + index]]
        tea_decrypt_block(block, 0, key)
        for index in range(8):
            nal[mapping[offset + index]] = block[index]
        offset += stride

    return drop_epb_03(nal, epbs) if epbs else length


def type1_fbit(word: int) -> int:
    w0 = (word >> 0) & 1
    w8 = (word >> 8) & 1
    w15 = (word >> 15) & 1
    w19 = (word >> 19) & 1
    w25 = (word >> 25) & 1
    w30 = (word >> 30) & 1
    w31 = (word >> 31) & 1
    t = w0 | w8
    return (
        w31
        ^ w15
        ^ t
        ^ (w8 & w19)
        ^ (w25 & (w0 ^ w19))
        ^ (w0 & (1 ^ w8) & w30)
        ^ ((1 ^ w0) & w19 & w30)
        ^ (w25 & w30 & (w8 ^ w19))
    ) & 1


def type1_is_b_step(step: int) -> bool:
    return step in (2, 8, 9, 10)


def type1_flip_mask_from_header(header: bytes | bytearray) -> int:
    if len(header) < 3:
        return 0
    b0, b1, b2 = header[0], header[1], header[2]
    mask = 0

    def set_bit(step: int) -> None:
        nonlocal mask
        mask |= 1 << step

    if b0 == 0x01 and b1 == 0xA8:
        if (b2 >> 7) & 1:
            set_bit(0)
        if (b2 >> 6) & 1:
            set_bit(1)
        if 1 ^ ((b2 >> 5) & 1):
            set_bit(2)
        if (b2 >> 4) & 1:
            set_bit(3)
        if (b2 >> 3) & 1:
            set_bit(4)
        if (b2 >> 1) & 1:
            set_bit(6)
        if b2 & 1:
            set_bit(7)
        set_bit(9)
        set_bit(12)
        return mask

    if b0 == 0x61:
        if (b2 >> 1) & 1:
            set_bit(0)
        if b2 & 1:
            set_bit(1)
        if 1 ^ ((b2 >> 5) & 1):
            set_bit(2)
        if (b2 >> 3) & 1:
            set_bit(4)
            set_bit(14)
        if (b2 >> 2) & 1:
            set_bit(5)
            set_bit(15)
        if (b2 >> 1) & 1:
            set_bit(6)
        if b2 & 1:
            set_bit(7)
        return mask

    if (b0 & 0x1F) == 1 and (b1 & 0xF0) == 0x90:
        if (b2 >> 7) & 1:
            set_bit(0)
        if (b2 >> 6) & 1:
            set_bit(1)
        if (b0 & 1) ^ ((b2 >> 5) & 1):
            set_bit(2)
        if (b2 >> 4) & 1:
            set_bit(3)
        if (b2 >> 3) & 1:
            set_bit(4)
        if (b2 >> 2) & 1:
            set_bit(5)
        if (b2 >> 1) & 1:
            set_bit(6)
        if b2 & 1:
            set_bit(7)
        if b0 & 1:
            for step in (9, 10, 11, 12, 14):
                set_bit(step)
        # Worker-oracle comparison across the 2018, 2021, and 2026 real
        # streams shows that step 13 follows header byte 1 bit 2.  The former
        # b0[0] XOR b0[6] rule produced 11,840 wrong cells in that corpus; for
        # example 41 9e 41 must use 0x7e86 while 41 9a 23 keeps 0x5ec0.
        if (b1 >> 2) & 1:
            set_bit(13)
        if b1 & 1:
            set_bit(15)
    return mask


def type1_g_flips(x: int, y: int, flip_mask: int) -> int:
    word = x | (y << 16)
    result = 0
    for step in range(16):
        f_value = type1_fbit(word) ^ ((flip_mask >> step) & 1)
        bit = f_value ^ (1 if type1_is_b_step(step) else 0)
        result = (result | (bit << (15 - step))) & M16
        word = (((word << 1) & M32) | bit) & M32
    return result


def type1_stride_f1(nal: bytes | bytearray) -> int:
    if len(nal) < 7:
        return 0
    little = nal[1] | (nal[2] << 8) | (nal[3] << 16) | (nal[4] << 24)
    index = little % len(_TYPE_STRIDE_BASE)
    return _TYPE_STRIDE_BASE[index] | nal[index + 1]


def decrypt_type1_new(
    nal: bytearray,
    *,
    stride: int,
    start: int = 64,
    guard: int = 17,
) -> int:
    """Decrypt a type-1 NAL in the post-type25 H5E mode."""
    length = len(nal)
    if length < 3 or stride < 4:
        return length
    header = bytes(nal[:3])
    flip_mask = type1_flip_mask_from_header(header)
    epbs = collect_epb_positions(nal)
    mapping = _rbsp_to_ebsp_map(nal)
    rbsp_len = len(mapping)

    offset = start
    while offset + guard <= rbsp_len and offset + 4 <= rbsp_len:
        x = nal[mapping[offset]] | (nal[mapping[offset + 1]] << 8)
        y = nal[mapping[offset + 2]] | (nal[mapping[offset + 3]] << 8)
        p1 = type1_g_flips(x, y, flip_mask)
        nal[mapping[offset]] = p1 & 0xFF
        nal[mapping[offset + 1]] = (p1 >> 8) & 0xFF
        nal[mapping[offset + 2]] = x & 0xFF
        nal[mapping[offset + 3]] = (x >> 8) & 0xFF
        offset += stride

    return drop_epb_03(nal, epbs) if epbs else length


def is_type25_enable(nal: bytes | bytearray) -> bool:
    return (
        len(nal) >= 4
        and (nal[0] & 0x1F) == 25
        and nal[2] == 0x01
        and nal[3] == 0x09
    )


class Session:
    """H5E stream-local decrypt mode selected by protocol NAL markers."""

    def __init__(self) -> None:
        self.new_mode = False
        self.type1_start = 64
        self.type1_guard = 17
        # Official worker calibration (2018/2020/2026 real streams): NALs
        # shorter than 129 bytes are shipped encrypted in both modes.
        self.min_decrypt_len = 129

    def on_nal(self, nal: bytearray) -> int:
        length = len(nal)
        if length < 1:
            return length
        nal_type = nal[0] & 0x1F

        if nal_type == 25:
            # Real streams alternate markers: ES3 0x09 switches to the new
            # mode and 0x06 switches back to the classic grid. The 2018
            # 1200-bitrate sample runs new-mode from marker NAL 969 to 9050
            # and classic on both sides, so the switch must be bidirectional.
            if length >= 4 and nal[2] == 0x01:
                self.new_mode = nal[3] == 0x09
            return length

        if not self.new_mode:
            if nal_type in (1, 5):
                if length < self.min_decrypt_len:
                    return length
                return decrypt_classic(nal)
            return length

        if nal_type == 5:
            return decrypt_type5_new(nal)

        if nal_type == 1:
            if length < self.min_decrypt_len:
                return length
            stride = type1_stride_f1(nal) or 511
            return decrypt_type1_new(
                nal,
                stride=stride,
                start=self.type1_start,
                guard=self.type1_guard,
            )

        return length

    def reset(self) -> None:
        self.new_mode = False


def expand_af_steal(data: bytearray, pkt_off: int, need: int) -> int:
    """Grow a TS adaptation field to absorb bytes removed from PES payload."""
    if need <= 0 or pkt_off + 188 > len(data):
        return 0
    afc = (data[pkt_off + 3] & 0x30) >> 4

    if afc == 1:
        af_len = min(need - 1, 182)
        steal = 1 + af_len
        old_payload = bytes(data[pkt_off + 4 : pkt_off + 188])
        data[pkt_off + 3] = (data[pkt_off + 3] & 0xCF) | 0x30
        data[pkt_off + 4] = af_len
        if af_len:
            data[pkt_off + 5] = 0
            if af_len > 1:
                data[pkt_off + 6 : pkt_off + 5 + af_len] = b"\xFF" * (af_len - 1)
        new_payload_len = 184 - steal
        start = pkt_off + 5 + af_len
        data[start : start + new_payload_len] = old_payload[:new_payload_len]
        return steal

    if afc in (2, 3):
        af_len = data[pkt_off + 4]
        payload_index = 5 + af_len
        if payload_index >= 188 or af_len >= 182:
            return 0
        old_payload_len = 188 - payload_index
        add = min(need, old_payload_len, 182 - af_len)
        if add <= 0:
            return 0
        old_payload = bytes(data[pkt_off + payload_index : pkt_off + 188])
        data[
            pkt_off + 5 + af_len : pkt_off + 5 + af_len + add
        ] = b"\xFF" * add
        new_af_len = af_len + add
        data[pkt_off + 4] = new_af_len
        new_payload_len = old_payload_len - add
        start = pkt_off + 5 + new_af_len
        data[start : start + new_payload_len] = old_payload[:new_payload_len]
        data[pkt_off + 3] = (
            (data[pkt_off + 3] & 0xCF) | (0x20 if new_payload_len == 0 else 0x30)
        )
        return add

    return 0


def decrypt_ts(data: bytes, vpid: int = 0x100) -> tuple[bytes, int]:
    """Decrypt one MPEG-TS buffer and return ``(plain_bytes, nal_count)``."""
    if len(data) < 188:
        return data, 0
    buffer = bytearray(data)
    session = Session()
    nal_count = _decrypt_ts_inplace(buffer, session, vpid)
    return bytes(buffer), nal_count


def _decrypt_ts_inplace(data: bytearray, session: Session, vpid: int) -> int:
    total = len(data)
    if total < 188:
        return 0
    pes = bytearray()
    spans: list[tuple[int, int, int]] = []
    nal_count = 0

    def flush() -> None:
        nonlocal nal_count
        if not pes:
            return

        base_skip = 0
        if len(pes) >= 9 and pes[:3] == b"\x00\x00\x01":
            base_skip = 9 + pes[8]
        if base_skip > len(pes):
            pes.clear()
            spans.clear()
            return

        pes_header = bytes(pes[:base_skip])
        es = bytearray(pes[base_skip:])
        starts: list[tuple[int, int]] = []
        index = 0
        while index + 3 < len(es):
            if (
                index + 4 <= len(es)
                and es[index : index + 4] == b"\x00\x00\x00\x01"
            ):
                starts.append((index, 4))
                index += 4
            elif es[index : index + 3] == b"\x00\x00\x01":
                starts.append((index, 3))
                index += 3
            else:
                index += 1

        new_es = bytearray()
        cursor = 0
        for nal_index, (position, start_code_len) in enumerate(starts):
            end = starts[nal_index + 1][0] if nal_index + 1 < len(starts) else len(es)
            if cursor < position:
                new_es += es[cursor:position]
            new_es += es[position : position + start_code_len]
            if position + start_code_len < end:
                nal = bytearray(es[position + start_code_len : end])
                new_len = session.on_nal(nal)
                new_es += nal[:new_len]
                nal_count += 1
            cursor = end
        if cursor < len(es):
            new_es += es[cursor:]

        new_pes = pes_header + bytes(new_es)
        capacity = sum(span[2] for span in spans)
        if capacity > len(new_pes):
            remaining = capacity - len(new_pes)
            for packet_offset, _, _ in reversed(spans):
                if remaining <= 0:
                    break
                remaining -= expand_af_steal(data, packet_offset, remaining)

            rebuilt: list[tuple[int, int, int]] = []
            for packet_offset, _, _ in spans:
                afc = (data[packet_offset + 3] & 0x30) >> 4
                if afc in (0, 2):
                    continue
                payload_index = (
                    4 if afc == 1 else 5 + data[packet_offset + 4]
                )
                if payload_index < 188:
                    rebuilt.append(
                        (packet_offset, payload_index, 188 - payload_index)
                    )
            spans[:] = rebuilt

        source_offset = 0
        for packet_offset, payload_index, payload_len in spans:
            available = max(0, len(new_pes) - source_offset)
            chunk_len = min(available, payload_len)
            if chunk_len:
                data[
                    packet_offset + payload_index : packet_offset + payload_index + chunk_len
                ] = new_pes[source_offset : source_offset + chunk_len]
            if chunk_len < payload_len:
                data[
                    packet_offset + payload_index + chunk_len : packet_offset + payload_index + payload_len
                ] = b"\xFF" * (payload_len - chunk_len)
            source_offset += payload_len
            if source_offset >= len(new_pes):
                break

        pes.clear()
        spans.clear()

    offset = 0
    while offset + 188 <= total:
        if data[offset] != 0x47:
            offset += 188
            continue
        pid = ((data[offset + 1] & 0x1F) << 8) | data[offset + 2]
        if pid != vpid:
            offset += 188
            continue
        pusi = (data[offset + 1] & 0x40) != 0
        afc = (data[offset + 3] & 0x30) >> 4
        if afc in (0, 2):
            offset += 188
            continue
        payload_index = 4 if afc == 1 else 5 + data[offset + 4]
        if payload_index >= 188:
            offset += 188
            continue
        if pusi:
            flush()
        payload_len = 188 - payload_index
        pes += data[offset + payload_index : offset + 188]
        spans.append((offset, payload_index, payload_len))
        offset += 188

    flush()
    return nal_count


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("usage: python cctv_h5e.py <input.ts> <output.ts>")
    with open(sys.argv[1], "rb") as source:
        raw = source.read()
    plain, count = decrypt_ts(raw)
    with open(sys.argv[2], "wb") as target:
        target.write(plain)
    print(f"decrypted NALs: {count}; bytes: {len(plain)}")
