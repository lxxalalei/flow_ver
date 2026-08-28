from __future__ import annotations

from unittest import mock

from education_resource_mcp.adapters import cctv_h5e


def test_classic_mode_stays_active_before_type25() -> None:
    session = cctv_h5e.Session()
    nal = bytearray([0x65]) + bytearray(199)  # type 5

    with mock.patch.object(
        cctv_h5e, "decrypt_classic", return_value=len(nal)
    ) as classic, mock.patch.object(cctv_h5e, "decrypt_type5_new") as new_mode:
        assert session.on_nal(nal) == len(nal)

    classic.assert_called_once_with(nal)
    new_mode.assert_not_called()
    assert session.new_mode is False


def test_type25_marker_enables_new_mode() -> None:
    session = cctv_h5e.Session()

    assert session.on_nal(bytearray([0x19, 0x00, 0x01, 0x09])) == 4
    assert session.new_mode is True


def test_type5_uses_dynamic_decrypt_after_type25() -> None:
    session = cctv_h5e.Session()
    session.on_nal(bytearray([0x19, 0x00, 0x01, 0x09]))
    nal = bytearray([0x65]) + bytearray(199)

    with mock.patch.object(
        cctv_h5e, "decrypt_type5_new", return_value=177
    ) as new_mode, mock.patch.object(cctv_h5e, "decrypt_classic") as classic:
        assert session.on_nal(nal) == 177

    new_mode.assert_called_once_with(nal)
    classic.assert_not_called()


def test_type1_uses_header_derived_stride_after_type25() -> None:
    session = cctv_h5e.Session()
    session.on_nal(bytearray([0x19, 0x00, 0x01, 0x09]))
    nal = bytearray([0x61]) + bytearray(199)

    with mock.patch.object(
        cctv_h5e, "type1_stride_f1", return_value=321
    ) as stride, mock.patch.object(
        cctv_h5e, "decrypt_type1_new", return_value=166
    ) as decrypt:
        assert session.on_nal(nal) == 166

    stride.assert_called_once_with(nal)
    decrypt.assert_called_once_with(nal, stride=321, start=64, guard=17)


def test_short_type1_is_untouched_in_new_mode() -> None:
    session = cctv_h5e.Session()
    session.on_nal(bytearray([0x19, 0x00, 0x01, 0x09]))
    nal = bytearray([0x61]) + bytearray(63)

    with mock.patch.object(cctv_h5e, "decrypt_type1_new") as decrypt:
        assert session.on_nal(nal) == len(nal)

    decrypt.assert_not_called()


def test_type5_does_not_drop_epb_created_by_decryption() -> None:
    nal = bytearray([0x65]) + bytearray([0x44] * 95)
    nal[5:21] = bytes(range(16))
    original_len = len(nal)

    def fake_tea(block: bytearray, pos: int, key: bytes) -> None:
        block[pos : pos + 8] = b"\x00\x00\x03\x44\x44\x44\x44\x44"

    with mock.patch.object(cctv_h5e, "tea_decrypt_block", fake_tea):
        new_len = cctv_h5e.decrypt_type5_new(nal)

    assert new_len == original_len
    assert nal[64:67] == b"\x00\x00\x03"


def test_type1_does_not_drop_epb_created_by_decryption() -> None:
    nal = bytearray([0x61]) + bytearray([0x44] * 95)
    # At the first cell, X=0x0300. A mocked P1=0 yields 00 00 00 03, which
    # contains a new 00 00 03 sequence that was not present in the encoded NAL.
    nal[64:68] = b"\x00\x03\x44\x44"
    original_len = len(nal)

    with mock.patch.object(cctv_h5e, "type1_g_flips", return_value=0):
        new_len = cctv_h5e.decrypt_type1_new(nal, stride=160)

    assert new_len == original_len
    assert nal[65:68] == b"\x00\x00\x03"
