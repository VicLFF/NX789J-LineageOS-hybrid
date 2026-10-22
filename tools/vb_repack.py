#!/usr/bin/env python3
"""Repack a vendor_boot (header v4) with a patched first_stage fstab, disabling AVB.

- parses the vendor_ramdisk (LZ4 legacy frame), unpacks the newc cpio
- patches first_stage_ramdisk/fstab.qcom: strips ,avb=... and ,avb_keys=...
- re-encodes the cpio, re-compresses as an LZ4 legacy frame using
  all-literal blocks (valid LZ4, ~0.4% overhead, no external tools needed)
- reassembles the vendor_boot image, updating header + ramdisk table sizes
"""
import struct, sys, os

PAGE = 4096

# ---------------- LZ4 legacy frame codec ----------------
def lz4_block_decompress(src):
    dst = bytearray(); i = 0; n = len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255: break
        dst += src[i:i+lit]; i += lit
        if i >= n: break
        off = src[i] | (src[i+1] << 8); i += 2
        ml = token & 0x0F
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255: break
        ml += 4
        start = len(dst) - off
        for k in range(ml):
            dst.append(dst[start + k])
    return bytes(dst)

def lz4_legacy_decompress(data):
    assert data[:4] == b'\x02\x21\x4c\x18'
    i, out = 4, bytearray()
    while i + 4 <= len(data):
        sz = struct.unpack('<I', data[i:i+4])[0]; i += 4
        if sz == 0: break
        out += lz4_block_decompress(data[i:i+sz]); i += sz
    return bytes(out)

def lz4_literal_block(block):
    n = len(block)
    if n < 15:
        return bytes([n << 4]) + block
    out = bytearray([0xF0])
    rem = n - 15
    while rem >= 255:
        out.append(255); rem -= 255
    out.append(rem)
    return bytes(out) + block

def lz4_legacy_compress(data, chunk=4 << 20):
    out = bytearray(b'\x02\x21\x4c\x18')
    for i in range(0, len(data), chunk):
        blk = lz4_literal_block(data[i:i+chunk])
        out += struct.pack('<I', len(blk))
        out += blk
    return bytes(out)

# ---------------- cpio (newc) ----------------
def cpio_parse(data):
    out, i = [], 0
    while True:
        if data[i:i+6] not in (b'070701', b'070702'):
            raise ValueError(f'bad cpio magic at {i}')
        hdr = data[i:i+110]
        f = [int(hdr[6+8*k:6+8*(k+1)], 16) for k in range(13)]
        mode, filesize, namesize = f[1], f[6], f[11]
        name = data[i+110:i+110+namesize-1].decode()
        pad = (4 - ((110 + namesize) % 4)) % 4
        dstart = i + 110 + namesize + pad
        out.append([hdr, name, mode, data[dstart:dstart+filesize]])
        i = dstart + filesize + ((4 - (filesize % 4)) % 4)
        if name == 'TRAILER!!!':
            break
    return out

def cpio_build(entries):
    out = bytearray()
    for hdr, name, mode, blob in entries:
        nm = name.encode() + b'\0'
        h = bytearray(hdr)
        h[6+8*6:6+8*7] = b'%08X' % len(blob)      # filesize
        h[6+8*12:6+8*13] = b'%08X' % 0            # checksum
        out += bytes(h) + nm
        out += b'\0' * ((4 - (len(out) % 4)) % 4)
        out += blob
        out += b'\0' * ((4 - (len(out) % 4)) % 4)
    return bytes(out)

# ---------------- vendor_boot ----------------
def get_header(b):
    return dict(
        hdr_version=struct.unpack('<I', b[8:12])[0],
        page=struct.unpack('<I', b[12:16])[0],
        kernel_addr=struct.unpack('<I', b[16:20])[0],
        ramdisk_addr=struct.unpack('<I', b[20:24])[0],
        ramdisk_size=struct.unpack('<I', b[24:28])[0],
        name=b[2080:2096],
        hdr_size=struct.unpack('<I', b[2096:2100])[0],
        dtb_size=struct.unpack('<I', b[2100:2104])[0],
        dtb_addr=struct.unpack('<Q', b[2104:2112])[0],
        tbl_size=struct.unpack('<I', b[2112:2116])[0],
        tbl_num=struct.unpack('<I', b[2116:2120])[0],
        tbl_esz=struct.unpack('<I', b[2120:2124])[0],
        bc_size=struct.unpack('<I', b[2124:2128])[0],
    )

def align(x, p=PAGE):
    return (x + p - 1) // p * p

AVB_KEYS = (b',avb_keys=/avb/q-gsi.avbpubkey:/avb/r-gsi.avbpubkey:/avb/s-gsi.avbpubkey:'
            b'/avb/t-gsi.avbpubkey:/avb/u-gsi.avbpubkey:/avb/v-gsi.avbpubkey')

def patch_fstab(text):
    before = text
    text = text.replace(AVB_KEYS, b'')
    text = text.replace(b',avb=vbmeta_system', b'')
    text = text.replace(b',avb=vbmeta', b'')
    return text, (before != text)

def main(src, dst, outdir=None):
    b = open(src, 'rb').read()
    assert b[:8] == b'VNDRBOOT'
    h = get_header(b)
    page = h['page']
    o_rd = page
    o_dtb = align(o_rd + h['ramdisk_size'], page)
    o_tbl = align(o_dtb + h['dtb_size'], page)
    o_bc = align(o_tbl + h['tbl_size'], page)
    print(f'page={page} ramdisk@{o_rd}+{h["ramdisk_size"]} dtb@{o_dtb}+{h["dtb_size"]} '
          f'table@{o_tbl}+{h["tbl_size"]} bootconfig@{o_bc}+{h["bc_size"]}')

    raw_rd = b[o_rd:o_rd + h['ramdisk_size']]
    cpio = lz4_legacy_decompress(raw_rd)
    print(f'ramdisk {len(raw_rd)} -> {len(cpio)}')
    entries = cpio_parse(cpio)
    print(f'cpio entries={len(entries)}')

    patched = 0
    for e in entries:
        if e[1] in ('first_stage_ramdisk/fstab.qcom', 'first_stage_ramdisk/fstab.sun'):
            new, changed = patch_fstab(e[3])
            if changed:
                e[3] = new
                patched += 1
                if outdir:
                    open(os.path.join(outdir, 'fstab_patched.txt'), 'wb').write(new)
            print(f'  fstab {e[1]}: {len(new)} bytes, changed={changed}')
    if not patched:
        print('!! no fstab patched'); return 1

    new_cpio = cpio_build(entries)
    new_rd = lz4_legacy_compress(new_cpio)
    print(f'new cpio {len(new_cpio)} -> lz4 {len(new_rd)}')

    dtb = b[o_dtb:o_dtb + h['dtb_size']]
    tbl = bytearray(b[o_tbl:o_tbl + h['tbl_size']])
    bc = b[o_bc:o_bc + h['bc_size']]
    if h['tbl_num'] > 0 and h['tbl_esz'] >= 4:
        for k in range(h['tbl_num']):
            off = k * h['tbl_esz']
            struct.pack_into('<I', tbl, off, len(new_rd))   # ramdisk_size
            struct.pack_into('<I', tbl, off + 4, 0)         # ramdisk_offset

    o_dtb2 = align(page + len(new_rd), page)
    o_tbl2 = align(o_dtb2 + len(dtb), page)
    o_bc2 = align(o_tbl2 + len(tbl), page)
    total = align(o_bc2 + len(bc), page)

    hdr = bytearray(b[:page])
    struct.pack_into('<I', hdr, 24, len(new_rd))
    struct.pack_into('<I', hdr, 2112, len(tbl))
    out = bytearray(total)
    out[:page] = hdr
    out[page:page+len(new_rd)] = new_rd
    out[o_dtb2:o_dtb2+len(dtb)] = dtb
    out[o_tbl2:o_tbl2+len(tbl)] = tbl
    out[o_bc2:o_bc2+len(bc)] = bc

    if len(out) < len(b):
        out += b'\0' * (len(b) - len(out))
    open(dst, 'wb').write(bytes(out))
    print(f'wrote {dst} {len(out)} bytes (source {len(b)})')
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
