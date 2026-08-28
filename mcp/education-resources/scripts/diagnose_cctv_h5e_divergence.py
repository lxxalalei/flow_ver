from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

from education_resource_mcp.adapters import cctv_h5e


@dataclass(frozen=True)
class NalRecord:
    index: int
    nal_type: int
    header: bytes
    payload: bytes


def _extract_video_es(ts: bytes, vpid: int) -> bytes:
    """Collect video PES payload bytes from an MPEG-TS buffer."""

    pes = bytearray()
    es = bytearray()

    def flush() -> None:
        if not pes:
            return
        skip = 0
        if len(pes) >= 9 and pes[:3] == b"\x00\x00\x01":
            skip = 9 + pes[8]
        if skip <= len(pes):
            es.extend(pes[skip:])
        pes.clear()

    for offset in range(0, len(ts) - 187, 188):
        if ts[offset] != 0x47:
            continue
        pid = ((ts[offset + 1] & 0x1F) << 8) | ts[offset + 2]
        if pid != vpid:
            continue
        pusi = (ts[offset + 1] & 0x40) != 0
        afc = (ts[offset + 3] & 0x30) >> 4
        if afc in (0, 2):
            continue
        payload_index = 4 if afc == 1 else 5 + ts[offset + 4]
        if payload_index >= 188:
            continue
        if pusi:
            flush()
        pes.extend(ts[offset + payload_index : offset + 188])
    flush()
    return bytes(es)


def _split_annex_b(es: bytes) -> list[NalRecord]:
    starts: list[tuple[int, int]] = []
    index = 0
    while index + 3 < len(es):
        if es[index : index + 4] == b"\x00\x00\x00\x01":
            starts.append((index, 4))
            index += 4
        elif es[index : index + 3] == b"\x00\x00\x01":
            starts.append((index, 3))
            index += 3
        else:
            index += 1

    records: list[NalRecord] = []
    for nal_index, (position, prefix_len) in enumerate(starts):
        end = starts[nal_index + 1][0] if nal_index + 1 < len(starts) else len(es)
        payload = es[position + prefix_len : end]
        if not payload:
            continue
        records.append(
            NalRecord(
                index=len(records),
                nal_type=payload[0] & 0x1F,
                header=payload[:3],
                payload=payload,
            )
        )
    return records


def _first_diff(left: bytes, right: bytes) -> int | None:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return None


def _hex_window(data: bytes, offset: int, radius: int = 16) -> str:
    start = max(0, offset - radius)
    end = min(len(data), offset + radius)
    return f"[{start}:{end}] {data[start:end].hex(' ')}"


def _packet_context(ts: bytes, byte_offset: int) -> dict[str, object]:
    packet_index = byte_offset // 188
    packet_start = packet_index * 188
    within = byte_offset - packet_start
    result: dict[str, object] = {
        "packet_index": packet_index,
        "packet_byte_offset": within,
    }
    if packet_start + 188 > len(ts) or ts[packet_start] != 0x47:
        result["valid_ts_packet"] = False
        return result

    result["valid_ts_packet"] = True
    result["pid"] = hex(((ts[packet_start + 1] & 0x1F) << 8) | ts[packet_start + 2])
    result["pusi"] = bool(ts[packet_start + 1] & 0x40)
    result["afc"] = (ts[packet_start + 3] & 0x30) >> 4
    result["continuity_counter"] = ts[packet_start + 3] & 0x0F
    return result


def _mode_details(encrypted_nals: list[NalRecord], target_index: int) -> dict[str, object]:
    new_mode = False
    target = encrypted_nals[target_index]
    for record in encrypted_nals[:target_index]:
        if record.nal_type == 25 and cctv_h5e.is_type25_enable(record.payload):
            new_mode = True

    details: dict[str, object] = {
        "new_mode_before": new_mode,
        "nal_type": target.nal_type,
        "header": target.header.hex(" "),
        "length": len(target.payload),
        "epb_count": len(cctv_h5e.collect_epb_positions(bytearray(target.payload))),
    }
    if target.nal_type == 25:
        details["type25_enable"] = cctv_h5e.is_type25_enable(target.payload)
    elif new_mode and target.nal_type == 5:
        key = target.payload[5:21]
        details["type5_stride"] = cctv_h5e.type5_stride_f5(key)
    elif new_mode and target.nal_type == 1:
        details["type1_stride"] = cctv_h5e.type1_stride_f1(target.payload)
        details["type1_flip_mask"] = hex(
            cctv_h5e.type1_flip_mask_from_header(target.payload[:3])
        )
    else:
        details["dispatch"] = "classic" if target.nal_type in (1, 5) else "unchanged"
    return details


def _print_first_ts_difference(native_ts: bytes, wasm_ts: bytes) -> None:
    diff = _first_diff(native_ts, wasm_ts)
    if diff is None:
        print("TS bytes are identical.")
        return

    print("\nFIRST TS-BYTE DIVERGENCE")
    print(f"absolute byte offset: {diff}")
    for key, value in _packet_context(native_ts, diff).items():
        print(f"native {key}: {value}")
    for key, value in _packet_context(wasm_ts, diff).items():
        print(f"wasm {key}: {value}")
    print(f"native: {_hex_window(native_ts, diff)}")
    print(f"wasm:   {_hex_window(wasm_ts, diff)}")


def diagnose(encrypted_ts: bytes, wasm_ts: bytes, *, vpid: int) -> int:
    native_ts, native_count = cctv_h5e.decrypt_ts(encrypted_ts, vpid=vpid)

    encrypted_nals = _split_annex_b(_extract_video_es(encrypted_ts, vpid))
    native_nals = _split_annex_b(_extract_video_es(native_ts, vpid))
    wasm_nals = _split_annex_b(_extract_video_es(wasm_ts, vpid))

    print(f"encrypted bytes: {len(encrypted_ts)}")
    print(f"native bytes:    {len(native_ts)}")
    print(f"wasm bytes:      {len(wasm_ts)}")
    print(f"native NAL count reported: {native_count}")
    print(
        "parsed NALs: "
        f"encrypted={len(encrypted_nals)} native={len(native_nals)} wasm={len(wasm_nals)}"
    )

    _print_first_ts_difference(native_ts, wasm_ts)

    common = min(len(encrypted_nals), len(native_nals), len(wasm_nals))
    for index in range(common):
        native = native_nals[index]
        wasm = wasm_nals[index]
        diff = _first_diff(native.payload, wasm.payload)
        if diff is None:
            continue

        encrypted = encrypted_nals[index]
        print("\nFIRST NAL DIVERGENCE")
        print(f"NAL index: {index}")
        for key, value in _mode_details(encrypted_nals, index).items():
            print(f"{key}: {value}")
        print(f"native length: {len(native.payload)}")
        print(f"wasm length:   {len(wasm.payload)}")
        print(f"first differing NAL byte: {diff}")
        print(f"encrypted sha256: {hashlib.sha256(encrypted.payload).hexdigest()}")
        print(f"native sha256:    {hashlib.sha256(native.payload).hexdigest()}")
        print(f"wasm sha256:      {hashlib.sha256(wasm.payload).hexdigest()}")
        print(f"encrypted: {_hex_window(encrypted.payload, diff)}")
        print(f"native:    {_hex_window(native.payload, diff)}")
        print(f"wasm:      {_hex_window(wasm.payload, diff)}")
        return 1

    if len(native_nals) != len(wasm_nals):
        print("\nNAL streams agree in common prefix but counts differ.")
        print(f"native={len(native_nals)} wasm={len(wasm_nals)}")
        return 1

    if native_ts != wasm_ts:
        print(
            "\nNAL payloads agree, but TS bytes differ. Investigate TS/PES rebuild, "
            "adaptation-field stuffing, or packetization before changing crypto."
        )
        return 1

    print("\nNo native/WASM divergence found.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Locate the first CCTV H5E native/WASM divergence at NAL and TS packet level."
        )
    )
    parser.add_argument("encrypted_ts", type=Path)
    parser.add_argument("wasm_ts", type=Path)
    parser.add_argument("--vpid", default="0x100", help="video PID, default 0x100")
    args = parser.parse_args()

    encrypted = args.encrypted_ts.read_bytes()
    wasm = args.wasm_ts.read_bytes()
    return diagnose(encrypted, wasm, vpid=int(args.vpid, 0))


if __name__ == "__main__":
    raise SystemExit(main())
