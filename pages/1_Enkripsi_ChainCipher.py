"""Halaman Streamlit: ChainCipher - enkripsi berantai bertema blockchain (Web3)."""
import base64
import binascii
import time

import pandas as pd
import streamlit as st

import chaincipher as cc

st.set_page_config(page_title="ChainCipher", page_icon="🔐", layout="wide")

# --- Gerbang akses: hanya user yang sudah login lewat halaman utama ---
if not st.session_state.get("authentication_status"):
    st.warning("Anda harus login terlebih dahulu untuk mengakses halaman ini.")
    try:
        st.page_link("app.py", label="Ke halaman login", icon="🔑")
    except Exception:
        st.info("Buka halaman utama aplikasi untuk login.")
    st.stop()

MAX_BYTES = 256 * 1024
MIN_PASSPHRASE = 12
KDF_LEVELS = {14: "Standar (16 MiB)", 15: "Kuat (32 MiB)", 16: "Sangat kuat (64 MiB)"}


# ------------------------------------------------------------------ helpers
def package_input(key: str) -> bytes | None:
    """Widget input paket CCv1 (hasil terakhir / Base64 / file). Mengembalikan bytes atau None."""
    options = ["Tempel Base64", "Unggah file .ccv1"]
    if "cc_result" in st.session_state:
        options.insert(0, "Hasil enkripsi terakhir")
    src = st.radio("Sumber paket", options, horizontal=True, key=f"{key}_src")
    if src == "Hasil enkripsi terakhir":
        return st.session_state["cc_result"]["package"]
    if src == "Tempel Base64":
        raw = st.text_area("Paket (Base64)", height=120, key=f"{key}_b64")
        if not raw.strip():
            return None
        try:
            return base64.b64decode("".join(raw.split()), validate=True)
        except (binascii.Error, ValueError):
            st.error("Teks Base64 tidak valid.")
            return None
    up = st.file_uploader("File paket (.ccv1)", key=f"{key}_file")
    if up is None:
        return None
    if up.size > MAX_BYTES + 512:
        st.error("File terlalu besar untuk demo ini (maks. 256 KiB).")
        return None
    return up.getvalue()


def short(h: str) -> str:
    return h if len(h) <= 20 else f"{h[:10]}…{h[-8:]}"


# ------------------------------------------------------------------ header
st.title("🔐 ChainCipher")
st.caption("Enkripsi berantai bertema blockchain: hash chain antar blok + pohon Merkle + HMAC (format CCv1).")
st.warning(
    "**Tujuan edukasi.** Algoritma ini adalah rancangan kombinasi/modifikasi untuk tugas kuliah dan **belum diaudit**. "
    "Jangan memasukkan private key, seed phrase, atau data rahasia asli. Untuk produksi gunakan AES-256-GCM atau "
    "ChaCha20-Poly1305 dari library teruji.",
    icon="⚠️",
)

tab_enc, tab_dec, tab_ver, tab_ana = st.tabs(
    ["🔐 Enkripsi", "🔓 Dekripsi", "🧾 Verifikasi Merkle", "📊 Analisis & Algoritma"]
)

# ------------------------------------------------------------------ ENKRIPSI
with tab_enc:
    st.subheader("Enkripsi data off-chain")
    st.caption(
        "Contoh kasus Web3: mengenkripsi metadata/dokumen sebelum disimpan off-chain (mis. IPFS), lalu "
        "meng-anchor Merkle root-nya ke blockchain sebagai bukti integritas."
    )
    mode = st.radio("Sumber data", ["Teks", "File"], horizontal=True, key="enc_mode")
    data, base_name = None, "pesan"
    if mode == "Teks":
        text = st.text_area("Pesan", height=140, key="enc_text")
        data = text.encode("utf-8") if text else None
    else:
        up = st.file_uploader("Pilih file (maks. 256 KiB)", key="enc_file")
        if up is not None:
            data, base_name = up.getvalue(), up.name

    c1, c2 = st.columns(2)
    pw = c1.text_input(f"Passphrase (min. {MIN_PASSPHRASE} karakter)", type="password", key="enc_pw")
    pw2 = c2.text_input("Ulangi passphrase", type="password", key="enc_pw2")
    level = st.select_slider(
        "Biaya KDF (scrypt)", options=list(KDF_LEVELS), value=14,
        format_func=KDF_LEVELS.get, key="enc_level",
    )

    if st.button("🔐 Enkripsi", type="primary", key="btn_enc"):
        if data is None:
            st.error("Masukkan teks atau pilih file terlebih dahulu.")
        elif len(data) > MAX_BYTES:
            st.error("Data terlalu besar untuk demo ini (maks. 256 KiB).")
        elif len(pw) < MIN_PASSPHRASE:
            st.error(f"Passphrase minimal {MIN_PASSPHRASE} karakter.")
        elif pw != pw2:
            st.error("Passphrase dan ulangannya tidak sama.")
        else:
            trace: list = []
            t0 = time.perf_counter()
            with st.spinner("Menurunkan kunci (scrypt) dan mengenkripsi…"):
                package = cc.encrypt(data, pw, n_log2=level, trace=trace)
            st.session_state["cc_result"] = {
                "package": package, "trace": trace, "plain_len": len(data),
                "elapsed": time.perf_counter() - t0, "name": base_name,
            }
            st.session_state.pop("cc_plain", None)
            # tab Dekripsi/Verifikasi langsung memakai paket yang baru dibuat
            st.session_state["dec_src"] = "Hasil enkripsi terakhir"
            st.session_state["ver_src"] = "Hasil enkripsi terakhir"

    res = st.session_state.get("cc_result")
    if res:
        info = cc.inspect_package(res["package"])
        st.success("Enkripsi berhasil.")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ukuran plaintext", f"{res['plain_len']:,} B")
        m2.metric("Ukuran paket", f"{len(res['package']):,} B")
        m3.metric("Jumlah blok (16 B)", f"{info['n_blocks']:,}")
        m4.metric("Waktu", f"{res['elapsed']:.2f} s")

        st.markdown("**Merkle root (siap di-anchor on-chain)**")
        st.code("0x" + info["root"], language=None)
        st.caption(
            "Simpan nilai ini di tempat tepercaya (mis. smart contract atau transaksi). Siapa pun dapat memeriksa "
            "bahwa ciphertext tidak berubah tanpa mengetahui passphrase (tab Verifikasi)."
        )

        b64 = base64.b64encode(res["package"]).decode()
        st.markdown("**Paket terenkripsi (Base64)**")
        if len(b64) <= 20_000:
            st.code(b64, language=None)
        else:
            st.info("Paket terlalu panjang untuk ditampilkan; gunakan tombol unduh.")
        st.download_button(
            "⬇️ Unduh paket (.ccv1)", res["package"], file_name=f"{res['name']}.ccv1",
            mime="application/octet-stream", key="dl_pkg",
        )

        with st.expander("Rantai blok (hash chain) dan daun Merkle"):
            df = pd.DataFrame(info["rows"][:200])
            for col in df.columns[1:]:
                df[col] = df[col].map(short)
            st.dataframe(df, hide_index=True)
            if info["n_blocks"] > 200:
                st.caption("Menampilkan 200 blok pertama.")
        with st.expander("Jejak enkripsi blok pertama (untuk laporan)"):
            st.dataframe(pd.DataFrame(res["trace"], columns=["Langkah", "State 16 byte (hex)"]), hide_index=True)

# ------------------------------------------------------------------ DEKRIPSI
with tab_dec:
    st.subheader("Dekripsi paket CCv1")
    pkg_in = package_input("dec")
    pw_d = st.text_input("Passphrase", type="password", key="dec_pw")
    if st.button("🔓 Dekripsi", type="primary", key="btn_dec"):
        if pkg_in is None:
            st.error("Masukkan paket terlebih dahulu.")
        elif not pw_d:
            st.error("Passphrase wajib diisi.")
        else:
            try:
                with st.spinner("Memverifikasi tag dan mendekripsi…"):
                    st.session_state["cc_plain"] = cc.decrypt(pkg_in, pw_d)
            except cc.ChainCipherError as exc:
                st.session_state.pop("cc_plain", None)
                st.error(str(exc))
            except Exception:
                st.session_state.pop("cc_plain", None)
                st.error("Terjadi kesalahan saat dekripsi.")

    plain = st.session_state.get("cc_plain")
    if plain is not None:
        st.success("Dekripsi berhasil; integritas terverifikasi.")
        try:
            st.text_area("Hasil dekripsi", plain.decode("utf-8"), height=160, disabled=True)
        except UnicodeDecodeError:
            st.info(f"Data biner ({len(plain):,} byte); gunakan tombol unduh.")
        d1, d2 = st.columns([1, 1])
        d1.download_button("⬇️ Unduh hasil", plain, file_name="hasil_dekripsi.bin", key="dl_plain")
        if d2.button("🧹 Bersihkan hasil dari layar", key="btn_clear"):
            st.session_state.pop("cc_plain", None)
            st.rerun()

# ------------------------------------------------------------------ VERIFIKASI MERKLE
with tab_ver:
    st.subheader("Verifikasi integritas tanpa passphrase")
    st.caption(
        "Cocokkan Merkle root paket dengan root yang di-anchor di sumber tepercaya. Kecocokan dengan root "
        "*di dalam* paket saja hanya membuktikan konsistensi internal, karena root dapat dihitung ulang oleh siapa pun."
    )
    pkg_v = package_input("ver")
    anchor = st.text_input("Merkle root yang di-anchor (hex, opsional)", placeholder="0x…", key="ver_anchor")
    if pkg_v is not None:
        try:
            info_v = cc.inspect_package(pkg_v)
            parsed = cc.parse_package(pkg_v)
        except cc.FormatError as exc:
            st.error(str(exc))
        else:
            v1, v2 = st.columns(2)
            v1.metric("Jumlah blok", f"{info_v['n_blocks']:,}")
            v2.metric("Konsistensi root internal", "Sesuai" if info_v["root_ok"] else "TIDAK sesuai")

            # Root dihitung ULANG dari ciphertext; root yang tertulis di paket tidak dipercaya begitu saja.
            computed_root = cc.merkle_root(cc.ciphertext_leaves(parsed.ct)).hex()
            trusted = info_v["root"]
            norm = anchor.strip().lower().removeprefix("0x")
            if norm:
                try:
                    bytes.fromhex(norm)
                    valid_anchor = len(norm) == 64
                except ValueError:
                    valid_anchor = False
                if not valid_anchor:
                    st.error("Format root anchor tidak valid (harus 64 karakter hex).")
                else:
                    trusted = norm  # root yang di-anchor adalah acuan tepercaya
                    if norm == computed_root:
                        st.success("Root hasil hitung ulang dari ciphertext SAMA dengan root yang di-anchor: ciphertext utuh.")
                    else:
                        st.error("Root hasil hitung ulang dari ciphertext BERBEDA dengan root yang di-anchor: ciphertext telah diubah atau ini paket lain.")

            st.markdown("**Bukti Merkle untuk satu blok** (cukup hash saudara, tanpa blok lain)")
            n = info_v["n_blocks"]
            idx = int(st.number_input("Nomor blok", 0, n - 1, 0, 1, key="ver_idx")) if n > 1 else 0
            leaves = cc.ciphertext_leaves(parsed.ct)
            proof = cc.merkle_proof(leaves, idx)
            ok = len(trusted) == 64 and cc.verify_proof(leaves[idx], idx, n, proof, bytes.fromhex(trusted))
            (st.success if ok else st.error)(
                f"Blok {idx} {'terbukti termasuk' if ok else 'TIDAK terbukti termasuk'} dalam root "
                f"{short(trusted)} (panjang bukti: {len(proof)} hash)."
            )
            if proof:
                st.dataframe(
                    pd.DataFrame({"Langkah (daun → root)": range(1, len(proof) + 1),
                                  "Hash saudara": [h.hex() for h in proof]}),
                    hide_index=True,
                )

# ------------------------------------------------------------------ ANALISIS & ALGORITMA
with tab_ana:
    st.subheader("Uji avalanche")
    st.caption("Membalik 1 bit plaintext lalu mengukur berapa persen bit ciphertext yang berubah (ideal ≈ 50%).")
    msg = st.text_input("Pesan uji", "Transfer 1.5 ETH ke 0xAbC123 untuk Budi sekarang!!", key="av_msg")
    raw_msg = msg.encode("utf-8")
    if raw_msg:
        max_bit = len(raw_msg) * 8 - 1
        bit = int(st.number_input(f"Indeks bit yang dibalik (0–{max_bit})", 0, max_bit, 0, 1))
        av = cc.avalanche_test(raw_msg, bit)
        a1, a2 = st.columns(2)
        a1.metric("Bit berubah di blok yang diubah", f"{av['per_block'][av['changed_block']]:.1%}")
        a2.metric("Bit berubah di seluruh ciphertext", f"{av['total_ratio']:.1%}")
        st.bar_chart(pd.DataFrame({"Proporsi bit berubah": av["per_block"]},
                                  index=[f"Blok {i}" for i in range(len(av["per_block"]))]))
        st.caption("Blok sebelum perubahan tetap sama (0%); blok sesudahnya berubah semua karena hash chain.")

    st.subheader("Deskripsi algoritma")
    st.code(
        "passphrase --scrypt(salt)--> enc_key || mac_key\n"
        "header     --SHA256d-------> C0  (genesis)\n"
        "untuk tiap blok plaintext 16 byte ke-i:\n"
        "    (RK_i, P_i) = SHAKE-256(enc_key || i || C_i)\n"
        "    c_i         = SPN 6 ronde: XOR kunci -> S-box dinamis -> shuffle byte -> difusi\n"
        "    C_(i+1)     = SHA256d(C_i || c_i)\n"
        "root = Merkle(SHA256d, c_0..c_n)\n"
        "tag  = HMAC-SHA256(mac_key, header || root || ciphertext)",
        language=None,
    )
    st.markdown(
        "| Lapisan | Fungsi | Kombinasi/modifikasi |\n|---|---|---|\n"
        "| Substitusi | S-box 256 byte dibangkitkan dari kunci | Dinamis per pesan, bukan tabel tetap |\n"
        "| Transposisi | Permutasi 16 posisi byte | Berbeda untuk setiap blok (turunan hash chain) |\n"
        "| Difusi | Rotasi + XOR berantai maju-mundur | 1 byte berubah memengaruhi seluruh blok |\n"
        "| Hash chain | Kunci blok ke-*i* bergantung pada ciphertext blok sebelumnya | Ide blockchain: ubah satu blok, semua blok setelahnya berubah |\n"
        "| Merkle tree | Root ciphertext + bukti per blok | Verifikasi tanpa kunci, siap di-anchor on-chain |\n"
        "| Autentikasi | HMAC-SHA256 (encrypt-then-MAC) | Tag diperiksa sebelum dekripsi |"
    )
    st.subheader("Praktik keamanan yang diterapkan")
    st.markdown(
        "- Kunci diturunkan dengan **scrypt** (salt acak 16 byte per pesan), passphrase dinormalisasi NFKC.\n"
        "- **Encrypt-then-MAC**; perbandingan tag **constant-time**; pesan error generik (tidak membedakan password salah vs data diubah).\n"
        "- Parameter KDF pada header **dibatasi** agar paket palsu tidak bisa menghabiskan memori server.\n"
        "- Pohon Merkle memakai **pemisah domain** daun/node dan **tidak menduplikasi node ganjil** (menghindari CVE-2012-2459).\n"
        "- Paket memiliki versi (`CCv1`), ada **known-answer test** dan unit test untuk tamper, chain, Merkle, dan avalanche.\n"
        "- Tidak ada kunci yang disimpan di disk; batas ukuran input diterapkan."
    )
    st.markdown(
        "**Batasan:** rancangan baru yang belum dianalisis kriptanalis (tidak ada bukti keamanan formal); panjang pesan "
        "tidak disembunyikan; Python tidak dapat menghapus rahasia dari memori secara andal."
    )