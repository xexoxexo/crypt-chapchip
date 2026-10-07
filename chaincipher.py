"""ChainCipher (format CCv1) - cipher edukasi bertema blockchain.

PERINGATAN: algoritma ini dirancang untuk PEMBELAJARAN (tugas kuliah) dan belum
pernah diaudit kriptografer. Jangan dipakai untuk melindungi private key, seed
phrase, atau aset nyata. Untuk produksi gunakan AES-256-GCM / ChaCha20-Poly1305
dari library yang teruji (mis. `cryptography`).

Alur enkripsi (kombinasi + modifikasi):

    passphrase --scrypt(salt)--> enc_key || mac_key
    header --SHA256d--> C0                      ("genesis block")
    untuk tiap blok plaintext 16 byte ke-i:
        (RK_i, P_i) = SHAKE-256(enc_key || i || C_i)   kunci ronde + permutasi unik blok
        c_i         = SPN 6 ronde: XOR kunci -> S-box dinamis -> shuffle byte -> difusi
        C_{i+1}     = SHA256d(C_i || c_i)              tautan hash antar blok (hash chain)
    root = Merkle(SHA256d, [c_0 .. c_n])               pohon Merkle (domain-separated, RFC 6962)
    tag  = HMAC-SHA256(mac_key, header || root || ciphertext)   encrypt-then-MAC

Format paket (biner):  header(29) || ciphertext || merkle_root(32) || tag(32)
    header = "CCv1" | n_log2 (1 byte) | salt (16 byte) | panjang ciphertext (8 byte)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import struct
import unicodedata
from dataclasses import dataclass

MAGIC = b"CCv1"
BLOCK = 16
ROUNDS = 6
SALT_LEN = 16
HASH_LEN = 32
KDF_R, KDF_P = 8, 1
KDF_LOG2_MIN, KDF_LOG2_MAX = 12, 16  # batas parameter scrypt (cegah DoS dari header palsu)
_HEADER_FMT = ">4sB16sQ"
HEADER_LEN = struct.calcsize(_HEADER_FMT)

Trace = list  # daftar (label, hex) untuk visualisasi edukasi


class ChainCipherError(Exception):
    """Basis semua error library ini."""


class FormatError(ChainCipherError):
    """Paket tidak valid / rusak (terdeteksi tanpa perlu kunci)."""


class AuthenticationError(ChainCipherError):
    """Tag HMAC tidak cocok. Sengaja generik: password salah dan data diubah tidak dibedakan."""


# --------------------------------------------------------------------------- hash helpers
def sha256d(data: bytes) -> bytes:
    """Double SHA-256, seperti hash blok & pohon Merkle di Bitcoin."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


# --------------------------------------------------------------------------- key derivation
def derive_keys(passphrase: str, salt: bytes, n_log2: int) -> tuple[bytes, bytes]:
    """scrypt -> (enc_key, mac_key). Passphrase dinormalisasi NFKC agar konsisten antar OS."""
    if not passphrase:
        raise ValueError("Passphrase tidak boleh kosong.")
    if not KDF_LOG2_MIN <= n_log2 <= KDF_LOG2_MAX:
        raise FormatError("Parameter KDF di luar batas yang diizinkan.")
    secret = unicodedata.normalize("NFKC", passphrase).encode("utf-8")
    okm = hashlib.scrypt(
        secret, salt=salt, n=1 << n_log2, r=KDF_R, p=KDF_P, dklen=64, maxmem=256 * 1024 * 1024
    )
    return okm[:32], okm[32:]


# --------------------------------------------------------------------------- cipher core
def _make_sbox(enc_key: bytes) -> tuple[bytes, bytes]:
    """S-box 256 byte unik per kunci (permutasi tak bias via pengurutan 64-bit acak) + inversnya."""
    stream = hashlib.shake_256(b"CCv1/sbox\x00" + enc_key).digest(256 * 8)
    keys = struct.unpack(">256Q", stream)
    sbox = bytes(sorted(range(256), key=keys.__getitem__))
    inv = bytearray(256)
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, bytes(inv)


def _block_schedule(enc_key: bytes, index: int, chain: bytes) -> tuple[list[bytes], list[int]]:
    """Kunci ronde (ROUNDS+1) dan permutasi 16 posisi, tergantung indeks blok dan hash chain."""
    n_key = BLOCK * (ROUNDS + 1)
    xof = hashlib.shake_256(
        b"CCv1/blk\x00" + enc_key + struct.pack(">Q", index) + chain
    ).digest(n_key + BLOCK * 8)
    round_keys = [xof[i * BLOCK:(i + 1) * BLOCK] for i in range(ROUNDS + 1)]
    pk = struct.unpack(">16Q", xof[n_key:])
    return round_keys, sorted(range(BLOCK), key=pk.__getitem__)


def _rotl8(x: int, n: int) -> int:
    return ((x << n) | (x >> (8 - n))) & 0xFF


def _diffuse(s: list[int]) -> None:
    """Difusi linear invertibel: 1 byte berubah -> seluruh blok terpengaruh."""
    for j in range(1, BLOCK):
        s[j] ^= _rotl8(s[j - 1], 1)
    for j in range(BLOCK - 2, -1, -1):
        s[j] ^= _rotl8(s[j + 1], 3)


def _undiffuse(s: list[int]) -> None:
    for j in range(0, BLOCK - 1):
        s[j] ^= _rotl8(s[j + 1], 3)
    for j in range(BLOCK - 1, 0, -1):
        s[j] ^= _rotl8(s[j - 1], 1)


def _enc_block(block: bytes, rks: list[bytes], perm: list[int], sbox: bytes, trace: Trace | None = None) -> bytes:
    def note(label: str, state: list[int]) -> None:
        if trace is not None:
            trace.append((label, bytes(state).hex()))

    s = list(block)
    note("Input (plaintext blok 0)", s)
    for r in range(ROUNDS):
        s = [s[i] ^ rks[r][i] for i in range(BLOCK)]
        note(f"Ronde {r + 1} - XOR kunci ronde", s)
        s = [sbox[b] for b in s]
        note(f"Ronde {r + 1} - S-box dinamis", s)
        s = [s[perm[i]] for i in range(BLOCK)]
        note(f"Ronde {r + 1} - shuffle byte", s)
        _diffuse(s)
        note(f"Ronde {r + 1} - difusi", s)
    s = [s[i] ^ rks[ROUNDS][i] for i in range(BLOCK)]
    note("Output (ciphertext blok 0, whitening akhir)", s)
    return bytes(s)


def _dec_block(block: bytes, rks: list[bytes], perm: list[int], inv_sbox: bytes) -> bytes:
    s = [block[i] ^ rks[ROUNDS][i] for i in range(BLOCK)]
    for r in range(ROUNDS - 1, -1, -1):
        _undiffuse(s)
        t = [0] * BLOCK
        for i in range(BLOCK):
            t[perm[i]] = s[i]
        s = [inv_sbox[b] ^ rks[r][i] for i, b in enumerate(t)]
    return bytes(s)


# --------------------------------------------------------------------------- hash chain
def _genesis(header: bytes) -> bytes:
    return sha256d(b"CCv1/genesis\x00" + header)


def _link(prev: bytes, ct_block: bytes) -> bytes:
    return sha256d(b"CCv1/link\x00" + prev + ct_block)


def _encrypt_blocks(padded: bytes, enc_key: bytes, header: bytes, trace: Trace | None = None) -> bytes:
    sbox, _ = _make_sbox(enc_key)
    chain = _genesis(header)
    out = []
    for idx in range(len(padded) // BLOCK):
        rks, perm = _block_schedule(enc_key, idx, chain)
        ct = _enc_block(padded[idx * BLOCK:(idx + 1) * BLOCK], rks, perm, sbox, trace if idx == 0 else None)
        out.append(ct)
        chain = _link(chain, ct)
    return b"".join(out)


def _decrypt_blocks(ct: bytes, enc_key: bytes, header: bytes) -> bytes:
    _, inv_sbox = _make_sbox(enc_key)
    chain = _genesis(header)
    out = []
    for idx in range(len(ct) // BLOCK):
        block = ct[idx * BLOCK:(idx + 1) * BLOCK]
        rks, perm = _block_schedule(enc_key, idx, chain)
        out.append(_dec_block(block, rks, perm, inv_sbox))
        chain = _link(chain, block)  # rantai dihitung dari ciphertext
    return b"".join(out)


# --------------------------------------------------------------------------- Merkle tree (RFC 6962)
def _leaf(ct_block: bytes) -> bytes:
    return sha256d(b"\x00" + ct_block)


def _node(left: bytes, right: bytes) -> bytes:
    return sha256d(b"\x01" + left + right)


def _split(n: int) -> int:
    """Pangkat dua terbesar yang < n (n >= 2)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _blocks(ct: bytes) -> list[bytes]:
    return [ct[i:i + BLOCK] for i in range(0, len(ct), BLOCK)]


def merkle_root(leaves: list[bytes]) -> bytes:
    """Root Merkle dari daftar hash daun. Node ganjil TIDAK diduplikasi (hindari CVE-2012-2459)."""
    if not leaves:
        raise ValueError("Tidak ada daun.")

    def mth(lo: int, hi: int) -> bytes:
        if hi - lo == 1:
            return leaves[lo]
        k = _split(hi - lo)
        return _node(mth(lo, lo + k), mth(lo + k, hi))

    return mth(0, len(leaves))


def merkle_proof(leaves: list[bytes], index: int) -> list[bytes]:
    """Audit path (bukti Merkle) untuk satu daun; urutan: dari daun menuju root."""
    if not 0 <= index < len(leaves):
        raise IndexError("Indeks blok di luar jangkauan.")

    def path(m: int, lo: int, hi: int) -> list[bytes]:
        n = hi - lo
        if n == 1:
            return []
        k = _split(n)
        if m < k:
            return path(m, lo, lo + k) + [merkle_root(leaves[lo + k:hi])]
        return path(m - k, lo + k, hi) + [merkle_root(leaves[lo:lo + k])]

    return path(index, 0, len(leaves))


def verify_proof(leaf_hash: bytes, index: int, n_leaves: int, proof: list[bytes], root: bytes) -> bool:
    """Verifikasi satu blok terhadap root tanpa memerlukan blok lain."""

    def rebuild(m: int, n: int, path: list[bytes]) -> bytes | None:
        if n == 1:
            return leaf_hash if not path else None
        if not path:
            return None
        k = _split(n)
        sibling, rest = path[-1], path[:-1]
        if m < k:
            sub = rebuild(m, k, rest)
            return None if sub is None else _node(sub, sibling)
        sub = rebuild(m - k, n - k, rest)
        return None if sub is None else _node(sibling, sub)

    if not 0 <= index < n_leaves:
        return False
    computed = rebuild(index, n_leaves, proof)
    return computed is not None and hmac.compare_digest(computed, root)


def ciphertext_leaves(ct: bytes) -> list[bytes]:
    return [_leaf(b) for b in _blocks(ct)]


# --------------------------------------------------------------------------- package API
@dataclass(frozen=True)
class Package:
    header: bytes
    n_log2: int
    salt: bytes
    ct: bytes
    root: bytes
    tag: bytes


def _tag(mac_key: bytes, header: bytes, ct: bytes, root: bytes) -> bytes:
    return hmac.new(mac_key, b"CCv1/tag\x00" + header + root + ct, hashlib.sha256).digest()


def parse_package(data: bytes) -> Package:
    """Validasi struktur paket. Tidak butuh kunci; tidak melakukan KDF."""
    if len(data) < HEADER_LEN + 2 * HASH_LEN + BLOCK:
        raise FormatError("Data terlalu pendek untuk paket CCv1.")
    header = data[:HEADER_LEN]
    magic, n_log2, salt, ct_len = struct.unpack(_HEADER_FMT, header)
    if magic != MAGIC:
        raise FormatError("Bukan paket CCv1 (magic tidak cocok).")
    if not KDF_LOG2_MIN <= n_log2 <= KDF_LOG2_MAX:
        raise FormatError("Parameter KDF di luar batas yang diizinkan.")
    if ct_len == 0 or ct_len % BLOCK:
        raise FormatError("Panjang ciphertext tidak valid.")
    if len(data) != HEADER_LEN + ct_len + 2 * HASH_LEN:
        raise FormatError("Ukuran paket tidak sesuai header (terpotong atau berlebih).")
    ct = data[HEADER_LEN:HEADER_LEN + ct_len]
    root = data[HEADER_LEN + ct_len:HEADER_LEN + ct_len + HASH_LEN]
    return Package(header, n_log2, salt, ct, root, data[-HASH_LEN:])


def encrypt(plaintext: bytes, passphrase: str, *, n_log2: int = 14,
            trace: Trace | None = None, _salt: bytes | None = None) -> bytes:
    """Enkripsi -> paket CCv1. `_salt` HANYA untuk vektor uji; produksi selalu salt acak."""
    if not KDF_LOG2_MIN <= n_log2 <= KDF_LOG2_MAX:
        raise ValueError("n_log2 harus antara 12 dan 16.")
    plaintext = bytes(plaintext)
    salt = _salt if _salt is not None else os.urandom(SALT_LEN)
    pad = BLOCK - len(plaintext) % BLOCK  # padding PKCS#7 (selalu 1..16 byte)
    padded = plaintext + bytes([pad]) * pad
    header = struct.pack(_HEADER_FMT, MAGIC, n_log2, salt, len(padded))
    enc_key, mac_key = derive_keys(passphrase, salt, n_log2)
    ct = _encrypt_blocks(padded, enc_key, header, trace)
    root = merkle_root(ciphertext_leaves(ct))
    return header + ct + root + _tag(mac_key, header, ct, root)


def decrypt(data: bytes, passphrase: str) -> bytes:
    """Dekripsi paket CCv1. Tag diverifikasi (constant-time) SEBELUM dekripsi dijalankan."""
    pkg = parse_package(data)
    if not hmac.compare_digest(merkle_root(ciphertext_leaves(pkg.ct)), pkg.root):
        raise FormatError("Merkle root tidak cocok: paket rusak atau diubah.")
    enc_key, mac_key = derive_keys(passphrase, pkg.salt, pkg.n_log2)
    if not hmac.compare_digest(_tag(mac_key, pkg.header, pkg.ct, pkg.root), pkg.tag):
        raise AuthenticationError("Autentikasi gagal: passphrase salah atau data telah diubah.")
    padded = _decrypt_blocks(pkg.ct, enc_key, pkg.header)
    pad = padded[-1]
    if not 1 <= pad <= BLOCK or padded[-pad:] != bytes([pad]) * pad:
        raise AuthenticationError("Autentikasi gagal: passphrase salah atau data telah diubah.")
    return padded[:-pad]


def inspect_package(data: bytes) -> dict:
    """Ringkasan publik paket (tanpa kunci): rantai hash, daun Merkle, status root."""
    pkg = parse_package(data)
    chain = _genesis(pkg.header)
    rows = []
    for idx, block in enumerate(_blocks(pkg.ct)):
        rows.append({
            "blok": idx,
            "ciphertext": block.hex(),
            "chain_hash (pembentuk kunci blok)": chain.hex(),
            "leaf_hash (Merkle)": _leaf(block).hex(),
        })
        chain = _link(chain, block)
    computed = merkle_root(ciphertext_leaves(pkg.ct))
    return {
        "n_log2": pkg.n_log2,
        "salt": pkg.salt.hex(),
        "n_blocks": len(rows),
        "root": pkg.root.hex(),
        "root_ok": hmac.compare_digest(computed, pkg.root),
        "rows": rows,
    }


def avalanche_test(message: bytes, bit_index: int = 0) -> dict:
    """Ubah 1 bit plaintext lalu bandingkan ciphertext (kunci tetap, khusus analisis)."""
    if not message:
        raise ValueError("Pesan tidak boleh kosong.")
    if not 0 <= bit_index < len(message) * 8:
        raise ValueError("bit_index di luar jangkauan.")
    enc_key = hashlib.sha256(b"CCv1/avalanche-demo").digest()
    flipped = bytearray(message)
    flipped[bit_index // 8] ^= 1 << (bit_index % 8)

    def run(m: bytes) -> bytes:
        pad = BLOCK - len(m) % BLOCK
        padded = m + bytes([pad]) * pad
        header = struct.pack(_HEADER_FMT, MAGIC, 14, bytes(SALT_LEN), len(padded))
        return _encrypt_blocks(padded, enc_key, header)

    c1, c2 = run(message), run(bytes(flipped))
    per_block = [
        sum(bin(a ^ b).count("1") for a, b in zip(c1[i:i + BLOCK], c2[i:i + BLOCK])) / (BLOCK * 8)
        for i in range(0, len(c1), BLOCK)
    ]
    changed = sum(bin(a ^ b).count("1") for a, b in zip(c1, c2))
    return {
        "changed_block": bit_index // 8 // BLOCK,
        "per_block": per_block,
        "total_ratio": changed / (len(c1) * 8),
    }