import asyncio
import pandas as pd
import re
import datetime
import os
import streamlit as st
import nest_asyncio
import plotly.express as px
import io
from playwright.async_api import async_playwright

# Konfigurasi Awal
nest_asyncio.apply()

if 'df_scrape' not in st.session_state:
    st.session_state.df_scrape = pd.DataFrame()

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

async def run_scraper(url_target, metric_places, placeholder_chart, placeholder_table):
    async with async_playwright() as p:
        # headless=True wajib untuk Cloud
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        
        try:
            st.toast("Membuka Inaproc...")
            await page.goto(url_target, wait_until="domcontentloaded", timeout=60000)
            
            all_results_dict = {}
            page_num = 1
            
            while page_num <= 10: # Batasi 10 halaman untuk tes stabilitas
                st.sidebar.write(f"Memproses Hal: {page_num}")
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(2)
                
                # Ambil data
                items = await page.evaluate("""
                    () => {
                        const data = [];
                        document.querySelectorAll('a').forEach(el => {
                            if(el.innerText.includes('Rp')) {
                                data.push({
                                    text: el.innerText,
                                    link: el.href
                                });
                            }
                        });
                        return data;
                    }
                """)
                
                for item in items:
                    if item['link'] not in all_results_dict:
                        lines = item['text'].split('\n')
                        all_results_dict[item['link']] = {
                            "Nama Produk": lines[0],
                            "Harga": clean_price(item['text']),
                            "Terjual": clean_terjual(item['text']),
                            "Link": item['link']
                        }

                # Update UI
                df = pd.DataFrame(list(all_results_dict.values()))
                df['Omzet'] = df['Harga'] * df['Terjual']
                st.session_state.df_scrape = df
                
                metric_places[0].metric("Produk", len(df))
                metric_places[2].metric("Omzet", f"Rp {df['Omzet'].sum():,}")
                placeholder_table.dataframe(df.sort_values("Omzet", ascending=False), use_container_width=True)

                # Tombol Next
                next_btn = page.locator("li.ant-pagination-next").last
                if await next_btn.is_visible() and not await next_btn.is_disabled():
                    await next_btn.click()
                    page_num += 1
                    await asyncio.sleep(3)
                else:
                    break
        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            await browser.close()

def main():
    st.title("Inaproc Scraper Tool")
    url = st.sidebar.text_input("URL", "https://katalog.inaproc.id/b-braun-medical-indonesia-7pol")
    
    m1, m2, m3 = st.columns(3)
    metrics = [m1.empty(), m2.empty(), m3.empty()]
    table_p = st.empty()
    
    if st.sidebar.button("Mulai"):
        asyncio.run(run_scraper(url, metrics, None, table_p))

    if not st.session_state.df_scrape.empty:
        csv = st.session_state.df_scrape.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button("Download CSV", csv, "data.csv", "text/csv")

if __name__ == "__main__":
    main()
