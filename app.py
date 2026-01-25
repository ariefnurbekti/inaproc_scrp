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
    """Memastikan browser terpasang di server Streamlit."""
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
    except:
        pass

if sys.platform != "win32":
    install_playwright()

# ==============================================================================
# 2. FUNGSI PEMBERSIH (Robust)
# ==============================================================================
def clean_price(text):
    try:
        # Cari angka setelah 'Rp'
        match = re.search(r'Rp\s?([\d.,]+)', text)
        if match:
            num_str = match.group(1).replace('.', '').replace(',', '')
            return int(num_str)
        return 0
    except:
        return 0

def clean_terjual(text):
    try:
        if not text or "Terjual" not in text: return 0
        val_str = text.split('Terjual')[-1].strip().lower()
        num = re.findall(r"[\d.,]+", val_str)
        if not num: return 0
        val = float(num[0].replace(',', '.'))
        if 'rb' in val_str: val *= 1000
        elif 'jt' in val_str: val *= 1000000
        return int(val)
    except:
        return 0

# ==============================================================================
# 3. ENGINE SCRAPER
# ==============================================================================
async def run_scraper(url_target, metrics, table_p):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        
        # Blokir gambar untuk kecepatan
        await page.route("**/*.{png,jpg,jpeg,gif,svg}", lambda route: route.abort())

        try:
            st.toast("Membuka halaman...")
            await page.goto(url_target, wait_until="domcontentloaded", timeout=60000)
            
            all_data = {}
            page_num = 1
            
            while page_num <= 15: # Limit hal untuk keamanan
                st.sidebar.write(f"⏳ Memproses Halaman {page_num}...")
                await page.wait_for_selector("a", timeout=10000)
                
                # Scroll untuk memicu lazy load
                await page.evaluate("window.scrollBy(0, 1500)")
                await asyncio.sleep(1.5)
                
                # Ambil semua elemen link yang kemungkinan adalah kartu produk
                cards = await page.query_selector_all("a")
                
                for card in cards:
                    text = await card.inner_text()
                    link = await card.get_attribute("href")
                    
                    if text and "Rp" in text and link:
                        if link not in all_data:
                            # Pembersihan Baris Teks
                            lines = [l.strip() for l in text.split('\n') if l.strip()]
                            
                            # Logika Penangkapan Data yang lebih aman
                            harga = clean_price(text)
                            terjual = clean_terjual(text)
                            
                            # Ambil baris pertama sebagai nama produk (biasanya)
                            nama = lines[0] if len(lines) > 0 else "N/A"
                            
                            all_data[link] = {
                                "Nama Produk": nama,
                                "Harga": harga,
                                "Terjual": terjual,
                                "Omzet": harga * terjual,
                                "Link": link
                            }

                # Sinkronisasi ke UI
                if all_data:
                    df = pd.DataFrame(list(all_data.values()))
                    st.session_state.df_scrape = df
                    
                    metrics[0].metric("Total Produk", len(df))
                    metrics[1].metric("Total Omzet", f"Rp {df['Omzet'].sum():,}")
                    table_p.dataframe(df.sort_values("Omzet", ascending=False), use_container_width=True)

                # Cek tombol Next
                next_btn = page.locator("li.ant-pagination-next").last
                is_visible = await next_btn.is_visible()
                if is_visible:
                    is_disabled = await next_btn.evaluate("n => n.classList.contains('ant-pagination-disabled')")
                    if is_disabled: break
                    await next_btn.click()
                    page_num += 1
                    await asyncio.sleep(3)
                else:
                    break

        except Exception as e:
            st.error(f"Terjadi Kendala: {e}")
        finally:
            await browser.close()

# ==============================================================================
# 4. DASHBOARD UI
# ==============================================================================
def main():
    st.set_page_config(page_title="Inaproc Intelligence", layout="wide")
    st.title("📊 Inaproc Market Intelligence")

    url_input = st.sidebar.text_input("URL Katalog:", "https://katalog.inaproc.id/b-braun-medical-indonesia-7pol")
    start_btn = st.sidebar.button("🚀 Mulai Scrape", use_container_width=True)

    c1, c2 = st.columns([1, 2])
    m_produk = c1.empty()
    m_omzet = c2.empty()
    st.divider()
    
    table_p = st.empty()

    if start_btn:
        st.session_state.df_scrape = pd.DataFrame()
        asyncio.run(run_scraper(url_input, [m_produk, None, m_omzet], table_p))

    if not st.session_state.df_scrape.empty:
        st.sidebar.divider()
        csv = st.session_state.df_scrape.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button("📥 Download CSV", csv, "data_inaproc.csv", "text/csv", use_container_width=True)

if __name__ == "__main__":
    main()
