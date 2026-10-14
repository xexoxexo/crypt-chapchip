import base64
import secrets
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import yaml
import streamlit_authenticator as stauth
from yaml.loader import SafeLoader
from streamlit_autorefresh import st_autorefresh

# --- Page Config ---
st.set_page_config(page_icon="📈", page_title="Crypto Dashboard & ChainCipher", layout="wide")

# -------------------------------------------------------------
# KONFIGURASI & PENYIMPANAN USER (config.yaml)
# -------------------------------------------------------------
CONFIG_PATH: Path = Path(__file__).resolve().parent / "config.yaml"

def save_config(cfg):
    """Simpan config (termasuk user baru yang mendaftar) ke config.yaml."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

def load_config():
    """Muat config.yaml. Jika belum ada / belum lengkap, dibuat otomatis."""
    cfg = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.load(f, Loader=SafeLoader) or {}

    changed = False
    if not cfg.get("cookie"):
        cfg["cookie"] = {
            "name": "crypto_dashboard_auth",
            "key": secrets.token_hex(32),
            "expiry_days": 30,
        }
        changed = True
    if not cfg.get("credentials") or cfg["credentials"].get("usernames") is None:
        cfg["credentials"] = {"usernames": {}}
        changed = True
    if changed:
        save_config(cfg)
    return cfg

config = load_config()

# Inisialisasi Authenticator
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)

# -------------------------------------------------------------
# HALAMAN LOGIN & SIGN UP
# -------------------------------------------------------------
auth_box = st.empty()
with auth_box.container():
    st.title("📈 Crypto Dashboard & ChainCipher")
    tab_login, tab_signup = st.tabs(["🔑 Login", "📝 Daftar Akun"])

    # --- Tab Login ---
    with tab_login:
        authenticator.login(
            location="main",
            fields={
                "Form name": "Masuk ke Dashboard",
                "Username": "Username (bukan nama lengkap)",
                "Password": "Password",
                "Login": "Masuk",
            },
        )
        status_now = st.session_state.get("authentication_status")
        if status_now is False:
            st.error("Username atau password salah.")
        elif status_now is None:
            st.info("Silakan login, atau buat akun baru di tab **Daftar Akun**.")

    # --- Tab Sign Up ---
    with tab_signup:
        if not st.session_state.get("authentication_status"):
            st.caption(
                "Untuk **login nanti, gunakan Username**. "
                "Password: 8-20 karakter, ada huruf besar, huruf kecil, angka, dan simbol (@$!%*?&)."
            )
            try:
                email_baru, username_baru, nama_baru = authenticator.register_user(
                    location="main",
                    captcha=False,
                    password_hint=False,
                    fields={
                        "Form name": "Buat Akun Baru",
                        "First name": "Nama depan",
                        "Last name": "Nama belakang",
                        "Email": "Email",
                        "Username": "Username (dipakai untuk login)",
                        "Password": "Password",
                        "Repeat password": "Ulangi password",
                        "Password hint": "Petunjuk password",
                        "Captcha": "Captcha",
                        "Register": "Daftar",
                    },
                )
                if email_baru:
                    save_config(config)
                    st.success(
                        f"Akun berhasil dibuat! Username login Anda: **{username_baru}**. "
                        "Silakan pindah ke tab **Login**."
                    )
            except Exception as e:
                st.error(e)

# Ambil status otentikasi & informasi user
authentication_status = st.session_state.get("authentication_status")
name = st.session_state.get("name")
username = st.session_state.get("username")

# --- LOGIKA OTENTIKASI & APLIKASI UTAMA ---
if authentication_status:
    auth_box.empty()  # sembunyikan form login/sign up

    # --- Sidebar Logout & Navigasi ---
    authenticator.logout(button_name="Logout", location="sidebar")
    st.sidebar.write(f"Selamat datang, **{name}**! 👋")
    st.sidebar.markdown("---")

    st.sidebar.header("📂 Navigasi Menu")
    menu_pilihan = st.sidebar.radio(
        "Pilih Fitur Aplikasi:",
        ["📈 Crypto Dashboard", "🔐 ChainCipher (Off-Chain & On-Chain)"]
    )
    st.sidebar.markdown("---")

    # =========================================================
    # MENU 1: CRYPTO DASHBOARD
    # =========================================================
    if menu_pilihan == "📈 Crypto Dashboard":
        st.sidebar.image(
            "https://res.cloudinary.com/crunchbase-production/image/upload/c_lpad,f_auto,q_auto:eco,dpr_1/z3ahdkytzwi1jxlpazje",
            width=50,
        )
        st.sidebar.header("⚙️ Refresh & Alert Settings")

        auto_refresh = st.sidebar.checkbox("Aktifkan Auto-Refresh Data", value=True)
        if auto_refresh:
            refresh_interval = st.sidebar.slider("Interval Refresh (Detik):", min_value=5, max_value=60, value=10)
            st_autorefresh(interval=refresh_interval * 1000, key="crypto_data_refresher")

        enable_sound = st.sidebar.checkbox("Aktifkan Alarm Suara Lonjakan", value=True)
        threshold_alert = st.sidebar.slider("Batas Lonjakan Harga (%) untuk Alarm:", min_value=0.5, max_value=10.0, value=2.0, step=0.5)

        st.sidebar.markdown("---")

        c1, c2 = st.columns([1, 8])
        with c1:
            st.image(
                "https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/thumbs/240/apple/285/chart-increasing_1f4c8.png",
                width=90,
            )

        st.markdown(
            """# **Crypto Dashboard**
            Aplikasi pemantau harga kripto *real-time* dari [Binance API](https://www.binance.com/).
            """
        )
        st.header("**Selected Price**")

        def play_alert_sound(sound_url):
            sound_html = f"""
                <audio autoplay style="display:none;">
                    <source src="{sound_url}" type="audio/mp3">
                </audio>
            """
            st.markdown(sound_html, unsafe_allow_html=True)

        def round_value(input_value):
            try:
                val = input_value.iloc[0] if hasattr(input_value, "iloc") else input_value
                val = float(val)
                return float(round(val, 2)) if abs(val) > 1 else float(round(val, 8))
            except Exception:
                return 0.0

        @st.cache_data(ttl=5)
        def load_data():
            url = "https://api.binance.com/api/v3/ticker/24hr"
            try:
                return pd.read_json(url)
            except Exception as e:
                st.error(f"Gagal mengambil data dari Binance API: {e}")
                return pd.DataFrame()

        df = load_data()

        if not df.empty:
            cryptoList = {
                "Price 1": "BTCUSDT",
                "Price 2": "ETHUSDT",
                "Price 3": "BNBUSDT",
                "Price 4": "XRPUSDT",
                "Price 5": "ADAUSDT",
                "Price 6": "DOGEUSDT",
                "Price 7": "SHIBUSDT",
                "Price 8": "DOTUSDT",
                "Price 9": "MATICUSDT",
            }

            cols = st.columns(3)
            sound_triggered = False
            BEEP_SOUND_URL = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"

            for i, (selected_crypto_label, default_symbol) in enumerate(cryptoList.items()):
                symbols_list = list(df.symbol)
                selected_crypto_index = symbols_list.index(default_symbol) if default_symbol in symbols_list else 0

                selected_crypto = st.sidebar.selectbox(
                    selected_crypto_label, df.symbol, index=selected_crypto_index, key=str(i)
                )

                col_df = df[df.symbol == selected_crypto]

                if not col_df.empty:
                    col_price = round_value(col_df.weightedAvgPrice)
                    percent_val = float(col_df.priceChangePercent.iloc[0])
                    col_percent = f"{percent_val:.2f}%"

                    if enable_sound and abs(percent_val) >= threshold_alert:
                        sound_triggered = True

                    target_col = cols[i % 3]
                    with target_col:
                        st.metric(
                            selected_crypto,
                            f"${col_price:,.2f}" if col_price > 1 else f"${col_price}",
                            col_percent
                        )

            if sound_triggered:
                st.warning(f"🔔 **ALERT!** Terdeteksi lonjakan harga melebihi {threshold_alert}%!")
                play_alert_sound(BEEP_SOUND_URL)

            st.header("")

            @st.cache_data
            def convert_df(dataframe):
                return dataframe.to_csv(index=False).encode("utf-8")

            csv = convert_df(df)
            st.download_button(
                label="Download data as CSV",
                data=csv,
                file_name="large_df.csv",
                mime="text/csv",
            )
            st.dataframe(df, height=400)

# =========================================================
    # MENU 2: CHAINCIPHER (Off-Chain & On-Chain)
    # =========================================================
    elif menu_pilihan == "🔐 ChainCipher (Off-Chain & On-Chain)":
        st.title("🔒 ChainCipher: Enkripsi Berantai & Bukti Integritas Web3")
        st.markdown(
            """
            *Konsep Web3:* Mengenkripsi data/metadata sensitif untuk disimpan secara **off-chain** (misalnya IPFS), 
            lalu menghasilkan **Merkle Root** sebagai sidik jari ringkas untuk di-*anchor* ke blockchain sebagai bukti integritas.
            """
        )

        try:
            import chaincipher as cc
        except ImportError:
            st.error("Modul `chaincipher.py` tidak ditemukan di direktori proyek!")
            cc = None

        if cc:
            tab_enc, tab_dec, tab_ver = st.tabs(["🔑 Enkripsi Data", "🔓 Dekripsi Data", "🔍 Inspeksi & Verifikasi Merkle"])

            # --- TAB 1: ENKRIPSI ---
            with tab_enc:
                st.subheader("Enkripsi Data Off-Chain")
                input_tipe = st.radio("Sumber Data:", ["Teks", "File"], key="enc_source_type")
                
                pesan_input = None
                if input_tipe == "Teks":
                    pesan_input = st.text_area("Masukkan teks rahasia:", "Contoh data rahasia untuk divalidasi ke blockchain.")
                else:
                    file_up = st.file_uploader("Unggah dokumen/file (maks. 256 KiB):", type=["txt", "pdf", "png", "json"], key="file_up_enc")
                    if file_up:
                        pesan_input = file_up.read()

                passphrase = st.text_input("Kata sandi / Passphrase (min. 12 karakter):", type="password", key="pass_enc_cc")

                if st.button("Proses Enkripsi"):
                    if not pesan_input:
                        st.warning("Silakan masukkan teks atau unggah file terlebih dahulu.")
                    elif len(passphrase) < 12:
                        st.warning("Kata sandi terlalu pendek (minimal 12 karakter).")
                    else:
                        with st.spinner("Menjalankan enkripsi berantai dan membangun pohon Merkle..."):
                            try:
                                data_bytes = pesan_input.encode('utf-8') if isinstance(pesan_input, str) else pesan_input
                                
                                # Memanggil fungsi encrypt dari chaincipher.py[cite: 9]
                                pkg_bytes = cc.encrypt(data_bytes, passphrase)
                                
                                # Encode bytes ke Base64 agar mudah disalin pengguna
                                pkg_b64 = base64.b64encode(pkg_bytes).decode('utf-8')
                                
                                # Ambil informasi merkle root menggunakan inspect_package[cite: 9]
                                info = cc.inspect_package(pkg_bytes)
                                
                                st.success("Enkripsi berhasil!")
                                st.text_area("Hasil Paket Ciphertext (Base64 / Format CCv1):", pkg_b64, height=150)
                                st.info(f"🌿 **Merkle Root (Sidik Jari untuk On-Chain):** `{info['root']}`")
                                st.caption("Simpan Merkle Root di atas ke smart contract/blockchain untuk membuktikan keutuhan data off-chain.")
                            except Exception as e:
                                st.error(f"Terjadi kesalahan saat proses enkripsi: {e}")

            # --- TAB 2: DEKRIPSI ---
            with tab_dec:
                st.subheader("Dekripsi Data Off-Chain")
                paket_b64_input = st.text_area("Tempel Paket Enkripsi (Base64):", key="pkg_b64_input", height=150)
                passphrase_dec = st.text_input("Kata sandi / Passphrase:", type="password", key="pass_dec_cc")

                if st.button("Proses Dekripsi"):
                    if not paket_b64_input or not passphrase_dec:
                        st.warning("Lengkapi data paket Base64 dan kata sandi.")
                    else:
                        try:
                            # Decode dari base64 kembali ke format bytes paket CCv1[cite: 9]
                            pkg_bytes = base64.b64decode(paket_b64_input.strip())
                            
                            # Memanggil fungsi decrypt dari chaincipher.py[cite: 9]
                            decrypted_data = cc.decrypt(pkg_bytes, passphrase_dec)
                            
                            st.success("Dekripsi berhasil! Data asli:")
                            try:
                                st.text_area("Isi Pesan/Data Asli:", decrypted_data.decode('utf-8'), height=150)
                            except:
                                st.download_button("Unduh Hasil Dekripsi File", data=decrypted_data, file_name="decrypted_file.bin")
                        except Exception as e:
                            st.error(f"Gagal mendekripsi. Periksa kembali kata sandi atau keutuhan data: {e}")

            # --- TAB 3: INSPEKSI & VERIFIKASI ---
            with tab_ver:
                st.subheader("Inspeksi Struktur Paket & Keutuhan Rantai Hash")
                paket_insp = st.text_area("Tempel Paket Enkripsi (Base64) untuk Diinspeksi:", key="pkg_insp_input", height=150)
                
                if st.button("Inspeksi Paket"):
                    if paket_insp:
                        try:
                            pkg_bytes = base64.b64decode(paket_insp.strip())
                            
                            # Memanggil fungsi inspect_package dari chaincipher.py[cite: 9]
                            info = cc.inspect_package(pkg_bytes)
                            
                            st.json({
                                "Parameter KDF (n_log2)": info["n_log2"],
                                "Salt (Hex)": info["salt"],
                                "Jumlah Blok Cipher": info["n_blocks"],
                                "Status Merkle Root Valid": info["root_ok"],
                                "Merkle Root (Hex)": info["root"]
                            })
                            
                            st.markdown("### Rincian Blok & Rantai Hash (Hash Chain)")
                            st.dataframe(pd.DataFrame(info["rows"]))
                        except Exception as e:
                            st.error(f"Gagal menginspeksi paket: {e}")
                    else:
                        st.warning("Masukkan data paket Base64 terlebih dahulu.")