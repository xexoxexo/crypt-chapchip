"""Unit test ChainCipher. Jalankan:  pytest -q"""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chaincipher as cc  # noqa: E402

PW = "passphrase-uji-12345"
FAST = 12  # n_log2 terendah agar test cepat


def flip(data: bytes, pos: int) -> bytes:
    b = bytearray(data)
    b[pos] ^= 0x01
    return bytes(b)


# ---------------------------------------------------------------- correctness
@pytest.mark.parametrize("n", [0, 1, 15, 16, 17, 31, 32, 100, 1000])
def test_roundtrip_various_lengths(n):
    msg = os.urandom(n)
    assert cc.decrypt(cc.encrypt(msg, PW, n_log2=FAST), PW) == msg


def test_roundtrip_unicode_and_nfkc_passphrase():
    msg = "Transfer 2 ETH ke dompet Budi 🚀 — 日本語".encode()
    pkg = cc.encrypt(msg, "ｐａｓｓｗｏｒｄ-ＦＵＬＬ-１２３", n_log2=FAST)  # fullwidth
    assert cc.decrypt(pkg, "password-FULL-123") == msg  # NFKC menyamakan keduanya


def test_known_answer_vector():
    """Mengunci perilaku algoritma: perubahan tak sengaja pada cipher akan gagal di sini."""
    expected = (
        "434376310c000102030405060708090a0b0c0d0e0f0000000000000020eb84fe6ae9954c59f3c98b3a0eebde2ef5421544ff5a05ca147e5b1ce090b1929bb4826646f9c535233d3d4c1f93cf731bcaae1c6947619e467c88034057814770b635d957e475c39aa88c04dac2d77691d381e1b4469102977ca392e1fe70b3"
    )
    pkg = cc.encrypt(b"ChainCipher KAT 0123456789", "correct horse battery staple",
                     n_log2=FAST, _salt=bytes(range(16)))
    assert pkg.hex() == expected
    assert cc.decrypt(pkg, "correct horse battery staple") == b"ChainCipher KAT 0123456789"


def test_two_encryptions_differ_random_salt():
    assert cc.encrypt(b"sama", PW, n_log2=FAST) != cc.encrypt(b"sama", PW, n_log2=FAST)


def test_identical_plaintext_blocks_give_distinct_ciphertext_blocks():
    """Tidak ada kebocoran pola ala ECB."""
    pkg = cc.parse_package(cc.encrypt(b"A" * 160, PW, n_log2=FAST))
    blocks = {pkg.ct[i:i + 16] for i in range(0, len(pkg.ct), 16)}
    assert len(blocks) == len(pkg.ct) // 16


# ---------------------------------------------------------------- primitives
def test_sbox_is_permutation_and_inverse():
    sbox, inv = cc._make_sbox(b"k" * 32)
    assert sorted(sbox) == list(range(256))
    assert all(inv[sbox[i]] == i for i in range(256))


def test_diffuse_roundtrip_random_states():
    rng = random.Random(1)
    for _ in range(200):
        s = [rng.randrange(256) for _ in range(16)]
        t = list(s)
        cc._diffuse(t)
        cc._undiffuse(t)
        assert t == s


def test_block_encrypt_decrypt_inverse():
    key, chain = os.urandom(32), os.urandom(32)
    sbox, inv = cc._make_sbox(key)
    rks, perm = cc._block_schedule(key, 7, chain)
    blk = os.urandom(16)
    assert cc._dec_block(cc._enc_block(blk, rks, perm, sbox), rks, perm, inv) == blk


# ---------------------------------------------------------------- authentication / tamper
def test_wrong_passphrase_rejected():
    pkg = cc.encrypt(b"rahasia", PW, n_log2=FAST)
    with pytest.raises(cc.AuthenticationError):
        cc.decrypt(pkg, "passphrase-lain-12345")


def test_empty_passphrase_rejected():
    with pytest.raises(ValueError):
        cc.encrypt(b"x", "", n_log2=FAST)


def test_tamper_ciphertext_detected_by_merkle_root():
    pkg = cc.encrypt(b"x" * 64, PW, n_log2=FAST)
    with pytest.raises(cc.FormatError):
        cc.decrypt(flip(pkg, cc.HEADER_LEN + 3), PW)


def test_tamper_ciphertext_and_recompute_root_still_rejected_by_hmac():
    """Penyerang tanpa kunci boleh menghitung ulang root, tapi tidak bisa memalsukan tag."""
    pkg = cc.encrypt(b"x" * 64, PW, n_log2=FAST)
    p = cc.parse_package(pkg)
    ct = flip(p.ct, 5)
    root = cc.merkle_root(cc.ciphertext_leaves(ct))
    forged = p.header + ct + root + p.tag
    with pytest.raises(cc.AuthenticationError):
        cc.decrypt(forged, PW)


def test_tamper_tag_and_salt_rejected():
    pkg = cc.encrypt(b"data", PW, n_log2=FAST)
    with pytest.raises(cc.AuthenticationError):
        cc.decrypt(flip(pkg, len(pkg) - 1), PW)  # tag
    with pytest.raises(cc.AuthenticationError):
        cc.decrypt(flip(pkg, 6), PW)  # salt


def test_tamper_root_and_length_rejected():
    pkg = cc.encrypt(b"data", PW, n_log2=FAST)
    p = cc.parse_package(pkg)
    with pytest.raises(cc.FormatError):
        cc.decrypt(flip(pkg, cc.HEADER_LEN + len(p.ct)), PW)  # root
    with pytest.raises(cc.FormatError):
        cc.decrypt(pkg[:-1], PW)  # terpotong


@pytest.mark.parametrize("blob", [b"", b"x" * 10, b"XXXX" + bytes(200), os.urandom(300)])
def test_garbage_input_is_format_error(blob):
    with pytest.raises(cc.FormatError):
        cc.decrypt(blob, PW)


def test_kdf_parameter_bounds_enforced():
    pkg = bytearray(cc.encrypt(b"data", PW, n_log2=FAST))
    pkg[4] = 31  # n_log2 berbahaya (DoS memori)
    with pytest.raises(cc.FormatError):
        cc.decrypt(bytes(pkg), PW)
    with pytest.raises(ValueError):
        cc.encrypt(b"x", PW, n_log2=31)


# ---------------------------------------------------------------- hash chain
def test_chain_propagates_change_to_all_later_blocks():
    key = os.urandom(32)
    header = bytes(cc.HEADER_LEN)
    a = bytearray(os.urandom(16 * 6))
    b = bytearray(a)
    b[16 * 1] ^= 0x01  # ubah blok 1
    ca = cc._encrypt_blocks(bytes(a), key, header)
    cb = cc._encrypt_blocks(bytes(b), key, header)
    blk = lambda c, i: c[i * 16:(i + 1) * 16]  # noqa: E731
    assert blk(ca, 0) == blk(cb, 0)
    assert all(blk(ca, i) != blk(cb, i) for i in range(1, 6))


def test_avalanche_ratio_near_half():
    r = cc.avalanche_test(b"Transfer 1.5 ETH ke 0xAbC123 untuk Budi sekarang!!", bit_index=3)
    assert 0.35 <= r["per_block"][r["changed_block"]] <= 0.65
    assert 0.40 <= r["total_ratio"] <= 0.60
    r2 = cc.avalanche_test(b"Transfer 1.5 ETH ke 0xAbC123 untuk Budi sekarang!!", bit_index=8 * 20)
    assert all(x == 0 for x in r2["per_block"][:r2["changed_block"]])  # blok sebelum perubahan tetap


# ---------------------------------------------------------------- Merkle
def test_merkle_known_small_trees():
    l = [bytes([i]) * 32 for i in range(3)]
    assert cc.merkle_root(l[:1]) == l[0]
    assert cc.merkle_root(l[:2]) == cc._node(l[0], l[1])
    assert cc.merkle_root(l) == cc._node(cc._node(l[0], l[1]), l[2])  # tanpa duplikasi node ganjil


def test_merkle_no_odd_node_duplication_collision():
    """[a,b,c] dan [a,b,c,c] harus punya root berbeda (CVE-2012-2459)."""
    l = [bytes([i]) * 32 for i in range(3)]
    assert cc.merkle_root(l) != cc.merkle_root(l + [l[2]])


@pytest.mark.parametrize("n", list(range(1, 34)))
def test_merkle_proofs_all_indices(n):
    leaves = [cc.sha256d(bytes([i])) for i in range(n)]
    root = cc.merkle_root(leaves)
    for i in range(n):
        proof = cc.merkle_proof(leaves, i)
        assert cc.verify_proof(leaves[i], i, n, proof, root)
        assert not cc.verify_proof(cc.sha256d(b"palsu"), i, n, proof, root)
        assert not cc.verify_proof(leaves[i], (i + 1) % n if n > 1 else 1, n, proof, root)


def test_inspect_package_public_view():
    info = cc.inspect_package(cc.encrypt(b"y" * 50, PW, n_log2=FAST))
    assert info["root_ok"] and info["n_blocks"] == 4 and len(info["rows"]) == 4
    assert info["rows"][0]["chain_hash (pembentuk kunci blok)"] != info["rows"][1]["chain_hash (pembentuk kunci blok)"]