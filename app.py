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

# Inisialisasi nest_asyncio untuk Streamlit
nest_asyncio.apply()

# Pastikan folder hasil tersedia
if not os.path.exists("hasil"):
    os.makedirs("hasil")

# Konfigurasi Loop untuk Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


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
# ENGINE SCRAPER
# ==============================================================================
async def run_scraper(url_target, metric_places, placeholder_chart, placeholder_table):
    all_results_dict = {}

    async with async_playwright() as p:
        # Launch browser (headless=True wajib untuk server)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            st.toast("Membuka katalog...")
            await page.goto(url_target, wait_until="networkidle", timeout=90000)

            page_num = 1
            while True:
                st.sidebar.markdown(f"### 📑 Status: Memproses Hal. {page_num}")

                # Scroll untuk memicu lazy loading
                for _ in range(5):
                    await page.mouse.wheel(0, 1000)
                    await asyncio.sleep(0.5)

                # Ekstraksi Data
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

                for item in current_page_data:
                    if item['Link'] not in all_results_dict:
                        item['Harga'] = clean_price(item['Harga_Raw'])
                        item['Terjual'] = clean_terjual(item['Terjual_Raw'])
                        item['Omzet'] = item['Harga'] * item['Terjual']
                        all_results_dict[item['Link']] = item

                # Update Dashboard Real-time
                if all_results_dict:
                    df_now = pd.DataFrame(list(all_results_dict.values()))
                    st.session_state.df_scrape = df_now

                    metric_places[0].metric("Total Produk", f"{len(df_now)}")
                    metric_places[1].metric("Total Terjual", f"{df_now['Terjual'].sum():,}")
                    metric_places[2].metric("Estimasi Omzet", f"Rp {df_now['Omzet'].sum():,}")

                    df_sorted = df_now.sort_values(by="Omzet", ascending=False)
                    fig = px.bar(df_sorted.head(10).sort_values("Omzet"), x="Omzet", y="Nama Produk",
                                 orientation='h', color="Omzet", color_continuous_scale="Viridis")
                    placeholder_chart.plotly_chart(fig, use_container_width=True, key=f"c_{page_num}")
                    placeholder_table.dataframe(df_sorted[["Nama Produk", "Harga", "Terjual", "Omzet"]],
                                                use_container_width=True, height=400)

                # Navigasi ke halaman berikutnya
                next_btn = page.locator("li.ant-pagination-next, .Pagination_chevron__3Mnyu").last
                if await next_btn.is_visible():
                    is_disabled = await next_btn.evaluate(
                        "n => n.classList.contains('ant-pagination-disabled') || n.getAttribute('aria-disabled') === 'true'")
                    if is_disabled: break

                    await next_btn.click(force=True)
                    page_num += 1
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(3)
                else:
                    break

        except Exception as e:
            st.error(f"Terjadi kesalahan: {e}")
        finally:
            await browser.close()


# ==============================================================================
# UI INTERFACE
# ==============================================================================
def main():
    st.set_page_config(page_title="Inaproc Analytics", layout="wide")

    if 'df_scrape' not in st.session_state:
        st.session_state.df_scrape = pd.DataFrame()

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
        st.session_state.df_scrape = pd.DataFrame()  # Reset data
        asyncio.run(run_scraper(url_input, metrics, chart_p, table_p))

        # Opsi Download setelah selesai
        if not st.session_state.df_scrape.empty():
            st.sidebar.success("✅ Scraping Selesai!")
            df_final = st.session_state.df_scrape.sort_values("Omzet", ascending=False)

            # Export ke Excel Memory Buffer
            import io
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_final.to_excel(writer, index=False)

            st.sidebar.download_button(
                label="📥 Download Hasil (.xlsx)",
                data=buffer.getvalue(),
                file_name=f"inaproc_data_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


if __name__ == "__main__":
    main()