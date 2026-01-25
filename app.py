import asyncio
import pandas as pd
import re
import datetime
import os
import sys
import streamlit as st
import nest_asyncio
import plotly.express as px
from playwright.async_api import async_playwright

# Konfigurasi Loop
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

nest_asyncio.apply()


# ==============================================================================
# FUNGSI HELPER
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
# ENGINE SCRAPER (OPTIMIZED FOR ALL PAGES)
# ==============================================================================
async def run_scraper(url_target, metric_places, placeholder_chart, placeholder_table):
    FOLDER_PENYIMPANAN = "hasil"
    all_results_dict = {}

    async with async_playwright() as p:
        # Gunakan slow_mo untuk kestabilan ekstra
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = await context.new_page()

        try:
            st.toast("Membuka katalog...")
            await page.goto(url_target, wait_until="networkidle", timeout=90000)

            page_num = 1
            retry_no_data = 0  # Counter untuk mencoba lagi jika data kosong

            while True:
                st.sidebar.markdown(f"### 📑 Status: Memproses Hal. {page_num}")

                # 1. SCROLL LEBIH DALAM (PENTING)
                # Scroll berkali-kali ke bawah untuk memicu semua data muncul
                for _ in range(6):
                    await page.mouse.wheel(0, 1200)
                    await asyncio.sleep(0.7)

                # 2. EKSTRAKSI DATA
                current_page_data = await page.evaluate("""
                    () => {
                        const results = [];
                        document.querySelectorAll('a').forEach(card => {
                            const text = card.innerText || "";
                            if (text.includes('Rp') && text.length > 50) {
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

                # Masukkan data ke dictionary
                new_items_count = 0
                for item in current_page_data:
                    if item['Link'] not in all_results_dict:
                        item['Harga'] = clean_price(item['Harga_Raw'])
                        item['Terjual'] = clean_terjual(item['Terjual_Raw'])
                        item['Omzet'] = item['Harga'] * item['Terjual']
                        all_results_dict[item['Link']] = item
                        new_items_count += 1

                # UPDATE DASHBOARD
                if all_results_dict:
                    df_now = pd.DataFrame(list(all_results_dict.values()))
                    st.session_state.df_scrape = df_now
                    metric_places[0].metric("Total Produk", f"{len(df_now)}")
                    metric_places[1].metric("Total Terjual", f"{df_now['Terjual'].sum():,}")
                    metric_places[2].metric("Estimasi Omzet", f"Rp {df_now['Omzet'].sum():,}")

                    df_sorted = df_now.sort_values(by="Omzet", ascending=False)
                    fig = px.bar(df_sorted.head(10).sort_values("Omzet"), x="Omzet", y="Nama Produk", orientation='h',
                                 color="Omzet", color_continuous_scale="Viridis")
                    placeholder_chart.plotly_chart(fig, use_container_width=True, key=f"c_{page_num}")
                    placeholder_table.dataframe(df_sorted[["Nama Produk", "Harga", "Terjual", "Omzet"]],
                                                use_container_width=True, height=400, key=f"t_{page_num}")

                # 3. LOGIKA NAVIGASI DENGAN TUNGGU EKSTRA
                next_btn = page.locator("li.ant-pagination-next, .Pagination_chevron__3Mnyu").last

                if await next_btn.is_visible():
                    # Cek apakah tombol benar-benar mati
                    is_disabled = await next_btn.evaluate("""
                        n => n.classList.contains('ant-pagination-disabled') || 
                             n.getAttribute('aria-disabled') === 'true' || 
                             n.parentElement.classList.contains('ant-pagination-disabled')
                    """)

                    if is_disabled:
                        # Jika terdeteksi mati, kita tunggu 3 detik lalu cek ulang (antisipasi lag)
                        await asyncio.sleep(3)
                        is_still_disabled = await next_btn.evaluate(
                            "n => n.classList.contains('ant-pagination-disabled') || n.parentElement.classList.contains('ant-pagination-disabled')")
                        if is_still_disabled:
                            st.sidebar.success("🏁 Selesai! Halaman terakhir tercapai.")
                            break

                    # Klik dan tunggu muat sempurna
                    try:
                        await next_btn.click(force=True)
                        page_num += 1
                        st.toast(f"Memuat halaman {page_num}...")
                        # Tunggu hingga network sepi (menandakan data baru sudah masuk)
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(4)  # Waktu aman tambahan
                    except:
                        break
                else:
                    # Jika tombol tidak ada, mungkin karena lag. Tunggu sebentar.
                    await asyncio.sleep(3)
                    if not await next_btn.is_visible(): break

        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            if all_results_dict:
                df_final = pd.DataFrame(list(all_results_dict.values()))
                raw_name = df_final['Nama Penjual'].iloc[0] if not df_final.empty else "Data"
                clean_name = re.sub(r'[^\w\s-]', '', raw_name).strip().replace(' ', '_')
                file_name = f"hasil/{clean_name}_{datetime.datetime.now().strftime('%d-%m-%Y')}.xlsx"
                df_final.sort_values("Omzet", ascending=False).to_excel(file_name, index=False)
                st.sidebar.success(f"💾 File Disimpan: {file_name}")
            await browser.close()


# ==============================================================================
# UI INTERFACE
# ==============================================================================
def main():
    st.set_page_config(page_title="Inaproc Analytics", layout="wide")
    if 'df_scrape' not in st.session_state: st.session_state.df_scrape = pd.DataFrame()

    st.markdown("<h2 style='color:#FF4B4B;'>📈 Inaproc Market Intelligence</h2>", unsafe_allow_html=True)

    url_input = st.sidebar.text_input("URL Katalog:", value="https://katalog.inaproc.id/b-braun-medical-indonesia-7pol")
    start_btn = st.sidebar.button("🚀 Mulai Scrape", use_container_width=True)

    m1, m2, m3 = st.columns(3)
    metrics = [m1.empty(), m2.empty(), m3.empty()]
    st.divider()

    c_left, c_right = st.columns([1, 1.2])
    chart_p = c_left.empty()
    table_p = c_right.empty()

    if start_btn:
        st.session_state.df_scrape = pd.DataFrame()
        asyncio.run(run_scraper(url_input, metrics, chart_p, table_p))


if __name__ == "__main__":
    main()
