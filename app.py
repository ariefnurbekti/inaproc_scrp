import asyncio
import pandas as pd
import re
import datetime
import os
import sys
import subprocess
import streamlit as st
import nest_asyncio
import plotly.express as px
import io
from playwright.async_api import async_playwright

# 1. SETUP LINGKUNGAN
nest_asyncio.apply()

if 'df_scrape' not in st.session_state:
    st.session_state.df_scrape = pd.DataFrame()

def install_playwright():
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
    except:
        pass

if sys.platform != "win32":
    install_playwright()

# ==============================================================================
# 2. DATA CLEANING UTILITIES
# ==============================================================================
def clean_price(text):
    try:
        match = re.search(r'Rp\s?([\d.,]+)', text)
        if match:
            num_str = match.group(1).replace('.', '').replace(',', '')
            return int(num_str)
        return 0
    except: return 0

def clean_terjual(text):
    try:
        if "Terjual" not in text: return 0
        val_str = text.split('Terjual')[-1].strip().lower()
        num = re.findall(r"[\d.,]+", val_str)
        if not num: return 0
        val = float(num[0].replace(',', '.'))
        if 'rb' in val_str: val *= 1000
        elif 'jt' in val_str: val *= 1000000
        return int(val)
    except: return 0

# ==============================================================================
# 3. ENGINE SCRAPER (STEALTH MODE)
# ==============================================================================
async def run_scraper(url_target, metrics, table_p):
    async with async_playwright() as p:
        # Gunakan user agent browser asli untuk menghindari blokir
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1366, 'height': 768}
        )
        page = await context.new_page()

        try:
            st.toast("Sedang membuka Inaproc (Mode Stealth)...")
            # Menunggu 'load' saja, bukan networkidle agar tidak timeout
            response = await page.goto(url_target, wait_until="load", timeout=90000)
            
            # Cek jika diblokir
            if response.status == 403 or response.status == 404:
                st.error(f"Akses Ditolak (Status {response.status}). Inaproc memblokir koneksi dari server ini.")
                return

            all_data = {}
            page_num = 1
            
            while page_num <= 10:
                st.sidebar.info(f"🔍 Memindai Halaman {page_num}...")
                
                # Tunggu minimal 5 detik agar konten sempat dimuat
                await asyncio.sleep(5)
                
                # Ambil semua teks dari link
                cards = await page.query_selector_all("a")
                
                found_on_page = 0
                for card in cards:
                    try:
                        text = await card.inner_text()
                        link = await card.get_attribute("href")
                        
                        if text and "Rp" in text and link and "/product/" in link:
                            if link not in all_data:
                                harga = clean_price(text)
                                terjual = clean_terjual(text)
                                lines = [l.strip() for l in text.split('\n') if l.strip()]
                                
                                all_data[link] = {
                                    "Nama Produk": lines[0] if lines else "N/A",
                                    "Harga": harga,
                                    "Terjual": terjual,
                                    "Omzet": harga * terjual,
                                    "Link": link if link.startswith('http') else f"https://katalog.inaproc.id{link}"
                                }
                                found_on_page += 1
                    except: continue

                # Update UI Dashboard
                if all_data:
                    df = pd.DataFrame(list(all_data.values()))
                    st.session_state.df_scrape = df
                    metrics[0].metric("Produk Ditemukan", len(df))
                    metrics[1].metric("Total Estimasi Omzet", f"Rp {df['Omzet'].sum():,}")
                    table_p.dataframe(df.sort_values("Omzet", ascending=False), use_container_width=True)

                if found_on_page == 0:
                    st.warning("Tidak menemukan produk di halaman ini. Mencoba scroll...")
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(2)

                # Navigasi Halaman
                next_btn = page.locator("li.ant-pagination-next").last
                if await next_btn.is_visible():
                    is_disabled = await next_btn.evaluate("n => n.classList.contains('ant-pagination-disabled') || n.getAttribute('aria-disabled') === 'true'")
                    if is_disabled: break
                    await next_btn.click(force=True)
                    page_num += 1
                else:
                    break

        except Exception as e:
            st.error(f"Koneksi Gagal: {e}")
        finally:
            await browser.close()

# ==============================================================================
# 4. DASHBOARD UI
# ==============================================================================
def main():
    st.set_page_config(page_title="Inaproc Intelligence", layout="wide")
    st.title("📊 Inaproc Market Intelligence")

    url_input = st.sidebar.text_input("URL Katalog:", "https://katalog.inaproc.id/jayamas-medica-industri")
    start_btn = st.sidebar.button("🚀 Mulai Scrape", use_container_width=True)

    m1, m2 = st.columns(2)
    metrics = [m1.empty(), m2.empty()]
    st.divider()
    table_p = st.empty()

    if start_btn:
        st.session_state.df_scrape = pd.DataFrame()
        asyncio.run(run_scraper(url_input, metrics, table_p))

    if not st.session_state.df_scrape.empty:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            st.session_state.df_scrape.to_excel(writer, index=False)
        st.sidebar.download_button("📥 Download Excel", buffer.getvalue(), "data.xlsx", use_container_width=True)

if __name__ == "__main__":
    main()
