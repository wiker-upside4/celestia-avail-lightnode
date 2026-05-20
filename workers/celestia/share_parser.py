"""Parse Celestia EDS shares to count network-wide blobs in a block.

Share format (v0, sparse / "blob" shares):
    bytes  0..28   namespace (29 bytes: 1B version + 28B id)
    byte   29      info byte (bit 0 = sequence_start, bits 1..7 = version)
    bytes  30..33  sequence length uint32 BE  — only if sequence_start
    rest           data (padded to 512B total share length)

Compact shares (TX namespace 0x00...01, IS_ROOT 0x00...02, etc.) follow
a different layout but live in the primary-reserved namespace range and
are filtered out before we look at the info byte.

EDS layout: extended data square is sq x sq shares. The original data
square (ODS) is the top-left quadrant of size (sq/2) x (sq/2). Only ODS
shares carry real block data; the other three quadrants are erasure parity.
"""
import base64
from typing import Iterable


SHARE_NS_BYTES = 29
NS_VERSION_OFFSET = 0
INFO_BYTE_OFFSET = 29
SEQ_LEN_OFFSET = 30
SEQ_LEN_SIZE = 4


def _is_reserved_namespace(ns: bytes) -> bool:
    """Primary-reserved: version=0x00 AND namespace_id bytes 1..27 all zero.
    The last byte (ns[28]) can be anything 0x00..0xff — the entire range is
    primary-reserved per Celestia spec (MaxPrimaryReservedNamespaceID =
    27 zero bytes + 0xff). Covers TX (0x01), IS_ROOT (0x02), PFB (0x04),
    PRIMARY_RESERVED_PADDING (0xfe), TAIL_PAD (0xff), etc.

    Secondary-reserved (parity / parity-padding): version byte = 0xff.
    """
    if ns[0] == 0xff:
        return True
    if ns[0] == 0 and all(b == 0 for b in ns[1:28]):
        return True
    return False


def count_blobs(shares_b64: list[str], eds_size: int) -> tuple[int, int, int]:
    """Return (blob_count, total_blob_bytes, namespace_count) for one block.

    shares_b64: data_square from share.GetEDS — eds_size*eds_size base64 shares
                in row-major order.
    eds_size:   side of the extended square (e.g. 64). ODS side is eds_size/2.
    """
    ods_size = eds_size // 2
    blob_count = 0
    total_bytes = 0
    namespaces: set[bytes] = set()

    for r in range(ods_size):
        row_off = r * eds_size  # row is in the full EDS, so stride = eds_size
        for c in range(ods_size):
            share = base64.standard_b64decode(shares_b64[row_off + c])
            ns = share[:SHARE_NS_BYTES]
            if _is_reserved_namespace(ns):
                continue
            info = share[INFO_BYTE_OFFSET]
            if (info & 0x01) != 1:
                continue
            seq_len = int.from_bytes(
                share[SEQ_LEN_OFFSET:SEQ_LEN_OFFSET + SEQ_LEN_SIZE], "big"
            )
            # Namespace-padding share: sequence_start=1, sequence_length=0, carrying
            # the next/previous user namespace to align blobs to namespace boundaries.
            # Don't count it as a real blob.
            if seq_len == 0:
                continue
            blob_count += 1
            total_bytes += seq_len
            namespaces.add(ns)

    return blob_count, total_bytes, len(namespaces)
