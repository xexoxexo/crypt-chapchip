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
st.set_page_config(page_icon="📈", page_title="Crypto Dashboard", layout="wide")

# -------------------------------------------------------------
# KONFIGURASI & PENYIMPANAN USER (config.yaml)
# -------------------------------------------------------------
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


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
            "key": secrets.token_hex(32),  # kunci acak, disimpan agar tidak berubah tiap rerun
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
# HALAMAN LOGIN & SIGN UP (hilang otomatis setelah berhasil login)
# -------------------------------------------------------------
auth_box = st.empty()
with auth_box.container():
    st.title("📈 Crypto Dashboard")
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
                "Untuk **login nanti, gunakan Username** (bukan nama lengkap atau email). "
                "Username: huruf/angka tanpa spasi. "
                "Password: 8-20 karakter, ada huruf besar, huruf kecil, angka, dan simbol (@$!%*?&)."
            )
            try:
                email_baru, username_baru, nama_baru = authenticator.register_user(
                    location="main",
                    captcha=False,        # ubah ke True jika ingin pakai captcha
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
                    save_config(config)   # simpan user baru (password otomatis ter-hash)
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

# --- LOGIKA OTENTIKASI ---
if authentication_status:
    auth_box.empty()  # sembunyikan form login/sign up

    # -------------------------------------------------------------
    # AREA DASHBOARD (Hanya tampil jika BERHASIL LOGIN)
    # -------------------------------------------------------------

    # --- Sidebar Logout & User Info ---
    authenticator.logout(button_name="Logout", location="sidebar")
    st.sidebar.write(f"Selamat datang, **{name}**! 👋")
    st.sidebar.markdown("---")

    # --- Sidebar Controls (Auto Refresh & Sound Alert) ---
    st.sidebar.image(
        "https://res.cloudinary.com/crunchbase-production/image/upload/c_lpad,f_auto,q_auto:eco,dpr_1/z3ahdkytzwi1jxlpazje",
        width=50,
    )

    st.sidebar.header("⚙️ Refresh & Alert Settings")

    # Kontrol Auto Refresh
    auto_refresh = st.sidebar.checkbox("Aktifkan Auto-Refresh Data", value=True)
    if auto_refresh:
        refresh_interval = st.sidebar.slider("Interval Refresh (Detik):", min_value=5, max_value=60, value=10)
        st_autorefresh(interval=refresh_interval * 1000, key="crypto_data_refresher")

    # Kontrol Sound Alert
    enable_sound = st.sidebar.checkbox("Aktifkan Alarm Suara Lonjakan", value=True)
    threshold_alert = st.sidebar.slider("Batas Lonjakan Harga (%) untuk Alarm:", min_value=0.5, max_value=10.0, value=2.0, step=0.5)

    st.sidebar.markdown("---")

    # --- Header Section ---
    c1, c2 = st.columns([1, 8])

    with c1:
        st.image(
            "https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/thumbs/240/apple/285/chart-increasing_1f4c8.png",
            width=90,
        )

    st.markdown(
        """# **Crypto Dashboard**
    A simple cryptocurrency price app pulling price data from the [Binance API](https://www.binance.com/en/support/faq/360002502072).
    """
    )

    st.header("**Selected Price**")

    # --- Helper Functions ---
    def play_alert_sound(sound_url):
        """Memutar suara notifikasi via HTML5 Audio secara otomatis."""
        sound_html = f"""
            <audio autoplay style="display:none;">
                <source src="{sound_url}" type="audio/mp3">
            </audio>
        """
        st.markdown(sound_html, unsafe_allow_html=True)

    def round_value(input_value):
        """Fungsi pembulatan aman untuk Pandas Series/Float."""
        try:
            val = input_value.iloc[0] if hasattr(input_value, "iloc") else input_value
            val = float(val)
            if abs(val) > 1:
                return float(round(val, 2))
            else:
                return float(round(val, 8))
        except Exception:
            return 0.0

    @st.cache_data(ttl=5)
    def load_data():
        """Mengambil data dari Binance API dengan cache 5 detik."""
        url = "https://api.binance.com/api/v3/ticker/24hr"
        try:
            df_res = pd.read_json(url)
            return df_res
        except Exception as e:
            st.error(f"Gagal mengambil data dari Binance API: {e}")
            return pd.DataFrame()

    # Load Market Data
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
            st.warning(f"🔔 **ALERT!** Terdeteksi lonjakan/penurunan harga melebihi {threshold_alert}% pada koin pilihan Anda!")
            play_alert_sound(BEEP_SOUND_URL)

        st.header("")

        # CSV Download & Data Table
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
