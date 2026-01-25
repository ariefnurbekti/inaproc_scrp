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

# 1. PENGATURAN AWAL (Wajib di baris pertama)
nest_asyncio.apply()

# Inisialisasi State agar tidak error saat dipanggil
if 'df_scrape' not in st.session_state:
    st.session_state.df_scrape = pd.DataFrame()

# ==============================================================================
# 2. AUTO-FIX ENVIRONTMENT (Memaksa instalasi browser di server)
# ==============================================================================
def setup_browser():
    """Fungsi untuk memaksa server menginstal Chromium jika belum ada."""
    if sys.platform != "win32":
        try:
            # Cek apakah folder executable browser ada
            path_check = os.path.expanduser("~/.cache/ms-playwright")
            if not os.path.exists(path_check):
                with st.status("🔧 Menyiapkan Sistem Browser (Mohon Tunggu...)", expanded=True) as status:
                    st.write("Mengunduh Chromium...")
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    st.write("Mengunduh sistem dependensi...")
                    subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
                    status.update(label="✅ Sistem Siap!", state="complete", expanded=False)
        except Exception as e:
            st.error(f"Gagal inisialisasi server: {e}")

# Jalankan pengecekan sistem
setup_browser()

# Sinkronisasi Loop khusus Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ==============================================================================
# 3. FUNGSI PEMBERSIH DATA
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
    if 'rb' in val_str: num *= 1000
    elif 'jt' in val_str: num *= 1000000
    return int(num)

# ==============================================================================
# 4. ENGINE SCRAPER (ANTI-TIMEOUT)
# ==============================================================================
async def run_scraper(url_target, metric_places, placeholder_chart, placeholder_table):
    all_results_dict = {}

    async with async_playwright() as p:
        # Launch dengan sandbox mati agar stabil di Linux/Docker
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        
        # Blokir elemen berat (Gambar & Iklan)
        await page.route("**/*.{png,jpg,jpeg,svg,gif,webp,css}", lambda route: route.abort())

        try:
            st.toast("Menghubungkan ke Inaproc...")
            # Menggunakan wait_until load agar lebih cepat dari networkidle
            await page.goto(url_target, wait_until="load", timeout=60000)
            
            page_num = 1
            while True:
                st.sidebar.info(f"📑 Memproses Halaman: {page_num}")
                
                # Scroll cepat untuk memicu lazy load
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                await asyncio.sleep(0.5)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

                # Ekstraksi Data
                current_page_data = await page.evaluate("""
                    () => {
                        const results = [];
                        document.querySelectorAll('a').forEach(card => {
                            const text = card.innerText || "";
                            if (text.includes('Rp')) {
                                const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                                const hIdx = lines.findIndex(l => l.includes('Rp'));
                                if (hIdx !== -1) {
                                    results.push({
                                        "Nama Produk": lines[hIdx - 1] || "N/A",
                                        "Harga_Raw": lines[hIdx] || "N/A",
                                        "Nama Penjual": lines[hIdx + 4] || "Unknown",
                                        "Terjual_Raw": lines.find(l => l.includes('Terjual')) || "0",
                                        "Link": card.href
                                    });
                                }
                            }
                        });
                        return results;
                    }
                """)

                # Update State & Dashboard
                for item in current_page_data:
                    if item['Link'] not in all_results_dict:
                        item['Harga'] = clean_price(item['Harga_Raw'])
                        item['Terjual'] = clean_terjual(item['Terjual_Raw'])
                        item['Omzet'] = item['Harga'] * item['Terjual']
                        all_results_dict[item['Link']] = item

                if all_results_dict:
                    df_temp = pd.DataFrame(list(all_results_dict.values()))
                    st.session_state.df_scrape = df_temp
                    
                    metric_places[0].metric("Produk", f"{len(df_temp)}")
                    metric_places[1].metric("Terjual", f"{df_temp['Terjual'].sum():,}")
                    metric_places[2].metric("Est. Omzet", f"Rp {df_temp['Omzet'].sum():,}")

                    df_sorted = df_temp.sort_values(by="Omzet", ascending=False)
                    fig = px.bar(df_sorted.head(10).sort_values("Omzet"), x="Omzet", y="Nama Produk", 
                                 orientation='h', color="Omzet", color_continuous_scale="Viridis")
                    placeholder_chart.plotly_chart(fig, use_container_width=True, key=f"c_{page_num}")
                    placeholder_table.dataframe(df_sorted[["Nama Produk", "Harga", "Terjual", "Omzet"]], use_container_width=True)

                # Tombol Lanjut
                next_btn = page.locator("li.ant-pagination-next, .Pagination_chevron__3Mnyu").last
                if await next_btn.is_visible():
                    disabled = await next_btn.evaluate("n => n.classList.contains('ant-pagination-disabled') || n.getAttribute('aria-disabled') === 'true'")
                    if disabled: break
                    await next_btn.click(force=True)
                    page_num += 1
                    await page.wait_for_load_state("load")
                    await asyncio.sleep(2)
                else:
                    break
        except Exception as e:
            st.error(f"Gagal mengambil data: {e}")
        finally:
            await browser.close()

# ==============================================================================
# 5. UI UTAMA
# ==============================================================================
def main():
    st.set_page_config(page_title="Inaproc Scraper", layout="wide")
    st.title("📊 Inaproc Market Intelligence")

    url_input = st.sidebar.text_input("URL Katalog:", "https://katalog.inaproc.id/b-braun-medical-indonesia-7pol")
    start_btn = st.sidebar.button("🚀 Jalankan Scraper", use_container_width=True)

    m1, m2, m3 = st.columns(3)
    metrics = [m1.empty(), m2.empty(), m3.empty()]
    st.divider()

    c1, c2 = st.columns([1, 1.2])
    chart_p = c1.empty()
    table_p = c2.empty()

    if start_btn:
        st.session_state.df_scrape = pd.DataFrame()
        asyncio.run(run_scraper(url_input, metrics, chart_p, table_p))

    # Cek tombol download
    if not st.session_state.df_scrape.empty:
        st.sidebar.divider()
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            st.session_state.df_scrape.to_excel(writer, index=False)
        
        st.sidebar.download_button(
            label="📥 Download Excel",
            data=buffer.getvalue(),
            file_name=f"data_inaproc_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

if __name__ == "__main__":
    main()
