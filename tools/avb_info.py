#!/usr/bin/env python3
"""Correct AVB vbmeta parser (big-endian per AVB spec).

Prints header summary + every descriptor (property / hashtree / hash / chain / cmdline).
"""
import hashlib
import struct
import sys

HDR = struct.Struct('>4sIIQQIQQQQQQQQQQQII48s80s')

ALGOS = {0: 'NONE', 1: 'SHA256_RSA2048', 2: 'SHA256_RSA4096',
         3: 'SHA256_RSA8192', 4: 'SHA512_RSA2048', 5: 'SHA512_RSA4096',
         6: 'SHA512_RSA8192'}

TAGS = {0: 'Property', 1: 'Hashtree', 2: 'Hash', 3: 'KernelCmdline',
        4: 'ChainPartition'}


def s(b):
    return b.split(b'\x00', 1)[0].decode('utf-8', 'replace')


def parse(path):
    data = open(path, 'rb').read()
    (magic, major, minor, auth_size, aux_size, algo,
     hash_off, hash_size, sig_off, sig_size,
     pub_off, pub_size, pkm_off, pkm_size,
     desc_off, desc_size, rb_index, flags, rb_loc,
     release, _reserved) = HDR.unpack_from(data, 0)

    print('== %s' % path)
    print('   magic=%r libavb=%d.%d auth=%d aux=%d' % (magic, major, minor, auth_size, aux_size))
    print('   algorithm=%s pub_size=%d rollback_index=%d flags=%d rb_loc=%d release=%s'
          % (ALGOS.get(algo, algo), pub_size, rb_index, flags, rb_loc, s(release)))
    if flags & 1:
        print('   FLAG bit0 = HASHTREE_DISABLED')
    if flags & 2:
        print('   FLAG bit1 = VERIFICATION_DISABLED')

    pk_off = 256 + auth_size + pub_off
    pk = data[pk_off:pk_off + pub_size]
    print('   pubkey_sha1=%s' % (hashlib.sha1(pk).hexdigest() if pk else '-'))

    base = 256 + auth_size + desc_off
    end = base + desc_size
    pos = base
    n = 0
    while pos + 16 <= end:
        tag, follow = struct.unpack_from('>QQ', data, pos)
        body = data[pos + 16:pos + 16 + follow]
        n += 1
        if tag == 0:
            klen, vlen = struct.unpack_from('>QQ', body, 0)
            key = s(body[16:16 + klen])
            val = s(body[16 + klen:16 + klen + vlen])
            print('   [%d] Property %s = %s' % (n, key, val[:90]))
        elif tag == 1:
            (dmv, img_size, tree_off, tree_size, dbs, hbs, fec_roots,
             fec_off, fec_size) = struct.unpack_from('>IQQQIIIQQ', body, 0)
            alg = s(body[56:88])
            pnl, saltl, digl, dflags = struct.unpack_from('>IIII', body, 88)
            pname = s(body[104:104 + pnl])
            print('   [%d] Hashtree "%s" image_size=%d tree_off=%d tree_size=%d '
                  'fec_off=%d fec_size=%d alg=%s flags=%d'
                  % (n, pname, img_size, tree_off, tree_size, fec_off, fec_size, alg, dflags))
        elif tag == 2:
            img_size, alg = struct.unpack_from('>Q32s', body, 0)
            pnl, saltl, digl, dflags = struct.unpack_from('>IIII', body, 40)
            pname = s(body[56:56 + pnl])
            print('   [%d] Hash "%s" image_size=%d alg=%s flags=%d'
                  % (n, pname, img_size, s(alg), dflags))
        elif tag == 3:
            print('   [%d] KernelCmdline %r' % (n, body[:80]))
        elif tag == 4:
            loc, pnl, pkl = struct.unpack_from('>III', body, 0)
            pname = s(body[12:12 + pnl])
            pkey = body[12 + pnl:12 + pnl + pkl]
            print('   [%d] Chain "%s" loc=%d key_sha1=%s'
                  % (n, pname, loc, hashlib.sha1(pkey).hexdigest() if pkey else '-'))
        else:
            print('   [%d] %s bytes=%d' % (n, TAGS.get(tag, tag), follow))
        pos += 16 + follow
    print('   total descriptors=%d' % n)
    print()


for p in sys.argv[1:]:
    parse(p)
