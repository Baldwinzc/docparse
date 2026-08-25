from __future__ import annotations

import struct

import pytest

pytest.importorskip("xlrd")

_BOF = 0x0809
_EOF = 0x000A
_DIMENSIONS = 0x0200
_BOUNDSHEET = 0x0085
_DATEMODE = 0x0022
_XF = 0x00E0
_LABEL = 0x0204
_NUMBER = 0x0203
_MERGECELLS = 0x00E5

_XF_GENERAL = 0
_XF_DATE = 1

_DRAFT_NAME = "报关单一般贸易"

_EOC = -2
_FREE = -1
_FAT = -3
_SEC_SIZE = 512
_MIN_STD_STREAM = 4096


def _rec(rtype: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HH", rtype, len(payload)) + payload


def _bof(dt: int) -> bytes:
    return _rec(_BOF, struct.pack("<HHHHII", 0x0600, dt, 1, 1997, 0, 0x0600))


def _eof() -> bytes:
    return _rec(_EOF)


def _datemode(system: int = 0) -> bytes:
    return _rec(_DATEMODE, struct.pack("<H", system))


def _xf_record(fmt_key: int) -> bytes:
    return _rec(_XF, struct.pack("<HHHBBBBIiH", 0, fmt_key, 0xFFF0, 0x20, 0, 0, 0xFC, 0, 0, 0))


def _name_bytes(name: str) -> bytes:
    if any(ord(ch) > 127 for ch in name):
        return bytes([len(name), 0x01]) + name.encode("utf-16-le")
    return bytes([len(name), 0x00]) + name.encode("ascii")


def _boundsheet(offset: int, name: str) -> bytes:
    return _rec(_BOUNDSHEET, struct.pack("<IBB", offset, 0, 0) + _name_bytes(name))


def _label(row: int, col: int, text: str, xf: int = _XF_GENERAL) -> bytes:
    if any(ord(ch) > 127 for ch in text):
        payload = struct.pack("<HB", len(text), 0x01) + text.encode("utf-16-le")
    else:
        payload = struct.pack("<HB", len(text), 0x00) + text.encode("ascii")
    return _rec(_LABEL, struct.pack("<HHH", row, col, xf) + payload)


def _number(row: int, col: int, value: float, xf: int = _XF_GENERAL) -> bytes:
    return _rec(_NUMBER, struct.pack("<HHHd", row, col, xf, value))


def _date(row: int, col: int, serial: float) -> bytes:
    return _number(row, col, serial, xf=_XF_DATE)


def _merged(ranges: list[tuple[int, int, int, int]]) -> bytes:
    payload = struct.pack("<H", len(ranges))
    for row_first, row_last, col_first, col_last in ranges:
        payload += struct.pack("<HHHH", row_first, row_last, col_first, col_last)
    return _rec(_MERGECELLS, payload)


def build_xls(sheets: list[tuple[str, bytes]]) -> bytes:
    """sheets: [(name, body_records)]，body 不含 BOF/DIMENSIONS/EOF。"""
    bodies = [_bof(0x0010) + _dimensions(body) + body + _eof() for _, body in sheets]
    globals_head = _bof(0x0005) + _datemode() + _xf_record(0) + _xf_record(14)
    offset = len(globals_head) + sum(len(_boundsheet(0, name)) for name, _ in sheets)
    offset += len(_eof())
    parts = [globals_head]
    for (name, _), body in zip(sheets, bodies, strict=True):
        parts.append(_boundsheet(offset, name))
        offset += len(body)
    parts.append(_eof())
    parts.extend(bodies)
    return _ole2_wrap(b"".join(parts))


def _dir_entry(
    name: str | None,
    etype: int,
    first_sid: int,
    size: int,
    child: int = -1,
) -> bytes:
    entry = bytearray(128)
    if name:
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        entry[0 : len(encoded)] = encoded
        struct.pack_into("<H", entry, 64, len(encoded))
    struct.pack_into("<B", entry, 66, etype)
    struct.pack_into("<B", entry, 67, 1)
    struct.pack_into("<i", entry, 68, -1)
    struct.pack_into("<i", entry, 72, -1)
    struct.pack_into("<i", entry, 76, child)
    struct.pack_into("<i", entry, 116, first_sid)
    struct.pack_into("<i", entry, 120, size)
    return bytes(entry)


def _ole2_wrap(stream: bytes) -> bytes:
    stream += b"\x00" * (-len(stream) % _SEC_SIZE)
    if len(stream) < _MIN_STD_STREAM:
        stream += b"\x00" * (_MIN_STD_STREAM - len(stream))
    n_stream_secs = len(stream) // _SEC_SIZE

    fat = [_FREE] * (_SEC_SIZE // 4)
    fat[0] = _FAT
    fat[1] = _EOC
    for idx in range(n_stream_secs):
        fat[2 + idx] = _EOC if idx == n_stream_secs - 1 else 3 + idx

    directory = (
        _dir_entry("Root Entry", 5, _EOC, 0, child=1)
        + _dir_entry("Workbook", 2, 2, len(stream))
        + _dir_entry(None, 0, 0, 0)
        + _dir_entry(None, 0, 0, 0)
    )

    header = bytearray(_SEC_SIZE)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HH", header, 24, 0x3E, 3)
    header[28:30] = b"\xfe\xff"
    struct.pack_into("<HH", header, 30, 9, 6)
    struct.pack_into("<i", header, 44, 1)
    struct.pack_into("<i", header, 48, 1)
    struct.pack_into("<i", header, 56, _MIN_STD_STREAM)
    struct.pack_into("<i", header, 60, _EOC)
    struct.pack_into("<i", header, 64, 0)
    struct.pack_into("<i", header, 68, _EOC)
    struct.pack_into("<i", header, 72, 0)
    struct.pack_into("<109i", header, 76, *([0] + [_FREE] * 108))
    return bytes(header) + struct.pack("<128i", *fat) + directory + stream


def _dimensions(body: bytes) -> bytes:
    max_row = 0
    max_col = 0
    pos = 0
    while pos + 4 <= len(body):
        rtype, size = struct.unpack_from("<HH", body, pos)
        pos += 4
        if rtype in {_LABEL, _NUMBER} and size >= 6:
            row, col = struct.unpack_from("<HH", body, pos)
            max_row = max(max_row, row + 1)
            max_col = max(max_col, col + 1)
        pos += size
    return _rec(_DIMENSIONS, struct.pack("<IIHHH", 0, max_row, 0, max_col, 0))


def draft_xls() -> bytes:
    sheet1 = (
        _label(0, 0, "中华人民共和国海关出口货物报关单")
        + _label(2, 0, "境内发货人")
        + _merged([(2, 2, 0, 2)])
        + _label(3, 0, "深圳市多科通讯有限公司")
        + _merged([(3, 3, 0, 2)])
        + _label(2, 4, "出口口岸")
        + _label(2, 5, "深圳湾")
        + _label(2, 8, "出口日期")
        + _date(2, 9, 46190.0)
        + _label(4, 4, "运输方式")
        + _label(5, 4, "公路运输")
        + _label(6, 3, "件数")
        + _number(6, 4, 40.0)
        + _label(7, 0, "项号")
        + _label(7, 1, "商品编号")
        + _label(7, 2, "商品名称及规格型号")
        + _label(7, 3, "数量")
        + _label(7, 4, "币制")
        + _number(8, 0, 1.0)
        + _label(8, 1, "4821900000")
        + _label(8, 2, "标签")
        + _number(8, 3, 100.0)
        + _label(8, 4, "美元")
    )
    sheet2 = (
        _label(0, 0, "INVOICE")
        + _label(1, 0, "发票号码:")
        + _label(1, 1, "DKTX-2606057")
        + _number(2, 0, 1.81)
    )
    return build_xls([(_DRAFT_NAME, sheet1), ("发票", sheet2)])
