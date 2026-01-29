import os
import sys
import subprocess
import asyncio
import pandas as pd
import streamlit as st
import nest_asyncio
from playwright.async_api import async_playwright

# 1. FIX OTOMATIS: Instalasi Browser saat Start-up
# Ini akan mendownload Chromium ke folder cache Streamlit secara otomatis
def install_playwright_auto():
    # Folder standar tempat Playwright menyimpan browser di Linux
    playwright_path = os.path.expanduser("~/.cache/ms-playwright")
    
    if not os.path.exists(playwright_path):
        st.info("Sistem sedang mengunduh browser untuk pertama kali. Mohon tunggu sekitar 1 menit...")
        try:
            # Menggunakan sys.executable untuk memastikan memakai env python yang benar
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
            st.success("Browser berhasil diinstal!")
        except Exception as e:
            st.error(f"Gagal menginstal browser secara otomatis: {e}")
            st.stop()

# Jalankan installer sebelum aplikasi render
install_playwright_auto()
nest_asyncio.apply()

# ==============================================================================
# 2. ENGINE SCRAPER
# ==============================================================================
async def run_scraper(url_target):
    async with async_playwright() as p:
        # Gunakan args tambahan agar stabil di container Cloud
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        
        # Gunakan Context untuk menyamarkan Bot (Stealth)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            st.toast("Menghubungkan ke Inaproc...")
            # Gunakan timeout yang cukup lama karena Inaproc sering lambat
            await page.goto(url_target, wait_until="domcontentloaded", timeout=60000)
            
            # Beri jeda agar JavaScript merender produk
            await asyncio.sleep(5)
            
            # Ambil data sederhana (Hanya Nama dan Harga sebagai contoh)
            data = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('a').forEach(el => {
                        if(el.innerText.includes('Rp')) {
                            results.push({
                                "Informasi": el.innerText.split('\\n').join(' | '),
                                "Link": el.href
                            });
                        }
                    });
                    return results;
                }
            """)
            return pd.DataFrame(data)
            
        except Exception as e:
            st.error(f"Terjadi kendala saat membaca halaman: {e}")
            return pd.DataFrame()
        finally:
            await browser.close()

# ==============================================================================
# 3. INTERFACE UTAMA
# ==============================================================================
def main():
    st.set_page_config(page_title="Inaproc Scraper", layout="wide")
    st.title("📊 Inaproc Auto-Intelligence")
    
    url_input = st.text_input("Masukkan URL Katalog Inaproc:", "https://katalog.inaproc.id/jayamas-medica-industri")
    
    if st.button("Mulai Ambil Data"):
        if url_input:
            df = asyncio.run(run_scraper(url_input))
            if not df.empty:
                st.write(f"Ditemukan {len(df)} entri:")
                st.dataframe(df, use_container_width=True)
                
                # Tombol Download
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download Data (CSV)", csv, "data.csv", "text/csv")
            else:
                st.warning("Tidak ada data produk yang ditemukan. Coba cek URL kembali.")

if __name__ == "__main__":
    main()
