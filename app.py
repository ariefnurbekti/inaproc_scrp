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

# ==============================================================================
# 1. INITIALIZATION & AUTO-INSTALLER
# ==============================================================================
nest_asyncio.apply()

def install_playwright_browsers():
    """Menginstal browser Chromium jika belum ada di server Streamlit."""
    try:
        with st.spinner("Menyiapkan infrastruktur browser di server (tahap ini hanya sekali)..."):
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
        st.success("Browser siap digunakan!")
    except Exception as e:
        st.error(f"Gagal menginstal browser otomatis: {e}")

# Cek path cache Playwright di Linux server (Streamlit Cloud)
if not os.path.exists("/home/appuser/.cache/ms-playwright") and sys.platform != "win32":
    install_playwright_browsers()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ==============================================================================
# 2. DATA CLEANING UTILITIES
# ==============================================================================
def clean_price(price_str):
    if not price_str or price_str == "N/A": return 0
    clean = re.sub(r'[^0-9,]', '', price_str)
    return int(clean.split(',')[0]) if clean else 0

def clean_terjual(text):
    if not text or "Terjual" not in text: return 0
    val_str = text.replace('Terjual', '').strip().lower()
    numeric_part = re.search(r'[\d.,]+', val_str)
    if not numeric_part: return 0
    num = float(numeric_part.group().replace(',', '.'))
    if 'rb' in val_str:
        num *= 1000
    elif 'jt' in val_str:
        num *= 1000000
    return int(num)

# ==============================================================================
# 3. CORE SCRAPER ENGINE (OPTIMIZED)
# ==============================================================================
async def run_scraper(url_target, metric_places, placeholder_chart, placeholder_table):
    all_results_dict = {}

    async with async_playwright() as p:
        # Launch browser dengan argumen tambahan untuk stabilitas di server
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()

        # OPTIMASI: Blokir gambar dan media agar tidak timeout
        await page.route("**/*.{png,jpg,jpeg,svg,gif,webp,woff,woff2}", lambda route: route.abort())

        try:
            st.toast("Menghubungkan ke server Inaproc...")
            
            # Gunakan domcontentloaded agar tidak menunggu background script yang lambat
            await page.goto(url_target, wait_until="domcontentloaded", timeout=60000)
            
            # Tunggu selektor produk muncul sebentar
            try:
                await page.wait_for_selector("a[href*='/product/']", timeout=15000)
            except:
                pass

            page_num = 1
            while True:
                st.sidebar.markdown(f"### 📑 Memproses Halaman: {page_num}")

                # Scroll untuk trigger lazy loading data produk
                for _ in range(5):
                    await page.mouse.wheel(0, 1000)
                    await asyncio.sleep(0.5)

                # Ekstraksi Data via Client-Side Script
                current_page_data = await page.evaluate("""
                    () => {
                        const results = [];
                        document.querySelectorAll('a').forEach(card => {
                            const text = card.innerText || "";
                            if (text.includes('Rp') && text.length > 40) {
                                const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                                const hargaIdx = lines.findIndex(l => l.includes('Rp'));
                                if (hargaIdx !== -1) {
                                    results.push({
                                        "Nama Produk": lines[hargaIdx - 1] || "N/A",
                                        "Harga_Raw": lines[hargaIdx] || "N/A",
                                        "Nama Penjual": lines[hargaIdx + 4] || "Unknown",
                                        "Terjual_Raw": lines.find(l => l.includes('Terjual')) || "0",
                                        "Link": card.href
                                    });
                                }
                            }
                        });
                        return results;
                    }
                """)

                # Update dictionary dengan data unik berdasarkan Link
                for item in current_page_data:
                    if item['Link'] not in all_results_dict:
                        item['Harga'] = clean_price(item['Harga_Raw'])
                        item['Terjual'] = clean_terjual(item['Terjual_Raw'])
                        item['Omzet'] = item['Harga'] * item['Terjual']
                        all_results_dict[item['Link']] = item

                # Sinkronisasi ke Dashboard Real-time
                if all_results_dict:
                    df_now = pd.DataFrame(list(all_results_dict.values()))
                    st.session_state.df_scrape = df_now
                    
                    metric_places[0].metric("Total Produk", f"{len(df_now)}")
                    metric_places[1].metric("Total Terjual", f"{df_now['Terjual'].sum():,}")
                    metric_places[2].metric("Estimasi Omzet", f"Rp {df_now['Omzet'].sum():,}")

                    df_sorted = df_now.sort_values(by="Omzet", ascending=False)
                    fig = px.bar(df_sorted.head(10).sort_values("Omzet"), x="Omzet", y="Nama Produk", 
                                 orientation='h', color="Omzet", color_continuous_scale="Viridis")
                    placeholder_chart.plotly_chart(fig, use_container_width=True, key=f"chart_{page_num}")
                    placeholder_table.dataframe(df_sorted[["Nama Produk", "Harga", "Terjual", "Omzet"]], 
                                                use_container_width=True, height=400)

                # Cek Navigasi Next Page
                next_btn = page.locator("li.ant-pagination-next, .Pagination_chevron__3Mnyu").last
                if await next_btn.is_visible():
                    is_disabled = await next_btn.evaluate("n => n.classList.contains('ant-pagination-disabled') || n.getAttribute('aria-disabled') === 'true'")
                    if is_disabled:
                        st.sidebar.success("🏁 Mencapai akhir halaman.")
                        break
                    
                    await next_btn.click(force=True)
                    page_num += 1
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(4) 
                else:
                    break

        except Exception as e:
            st.error(f"Terjadi kendala teknis: {e}")
        finally:
            await browser.close()

# ==============================================================================
# 4. USER INTERFACE (STREAMLIT MAIN)
# ==============================================================================
def main():
    st.set_page_config(page_title="Inaproc Market Intelligence", layout="wide", page_icon="📊")
    
    if 'df_scrape' not in st.session_state:
        st.session_state.df_scrape = pd.DataFrame()

    st.markdown("<h2 style='color:#FF4B4B;'>📊 Inaproc Market Intelligence</h2>", unsafe_allow_html=True)
    st.info("Masukkan URL Katalog Toko di sidebar lalu klik tombol mulai.")

    # Sidebar
    st.sidebar.header("Konfigurasi")
    url_input = st.sidebar.text_input("URL Katalog Inaproc:", value="https://katalog.inaproc.id/b-braun-medical-indonesia-7pol")
    start_btn = st.sidebar.button("🚀 Mulai Scrape Data", use_container_width=True)

    # Dashboard Slots
    m1, m2, m3 = st.columns(3)
    metrics = [m1.empty(), m2.empty(), m3.empty()]
    st.divider()

    c_left, c_right = st.columns([1, 1.2])
    chart_p = c_left.empty()
    table_p = c_right.empty()

    if start_btn:
        st.session_state.df_scrape = pd.DataFrame() # Reset
        asyncio.run(run_scraper(url_input, metrics, chart_p, table_p))
        
        if not st.session_state.df_scrape.empty():
            st.sidebar.success("Proses Selesai!")
            df_final = st.session_state.df_scrape.sort_values("Omzet", ascending=False)
            
            # Export ke Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_final.to_excel(writer, index=False)
            
            st.sidebar.download_button(
                label="📥 Download Data (.xlsx)",
                data=buffer.getvalue(),
                file_name=f"inaproc_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

if __name__ == "__main__":
    main()
