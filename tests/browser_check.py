"""Optional real-browser workflow; requires Playwright + Chromium, never production data."""
from pathlib import Path
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from server import create_server
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory() as temp:
        server = create_server(Path(temp) / 'browser-fictional.db', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                executable = os.environ.get('CHROMIUM') or shutil.which('chromium')
                browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
                page = browser.new_page(viewport={'width':1440,'height':1100}, device_scale_factor=1)
                errors=[]
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('#staff-pin').fill(server.staff_pin); page.locator('#staff-login-form button').click()
                expect(page.locator('#connection')).to_have_text('Local engine connected')
                expect(page.locator('#stats')).to_contain_text('Patients waiting')
                page.locator('[data-register]').click()
                page.locator('#new-name').fill('Missing Severity Fictional')
                page.locator('#new-age').fill('30')
                assert not page.locator('#registration-form').evaluate('(f) => f.checkValidity()')
                page.locator('#registration-dialog [data-close]').first.click()
                for name,age,severity in [('Avery Fictional',31,4),('Morgan Fictional',40,1),('Sky Fictional',22,2)]:
                    page.locator('[data-register]').click()
                    page.locator('#new-name').fill(name); page.locator('#new-age').fill(str(age))
                    page.locator(f'input[name="severity"][value="{severity}"]').check()
                    page.locator('#registration-form button[type=submit]').click()
                    expect(page.locator('#registration-dialog')).not_to_be_visible()
                screenshots=ROOT / 'build' / 'screenshots'; screenshots.mkdir(exist_ok=True)
                page.screenshot(path=str(screenshots/'dashboard-desktop.png'), full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page overflows'
                page.screenshot(path=str(screenshots/'dashboard-mobile.png'), full_page=True)
                page.set_viewport_size({'width':1440,'height':1100})
                page.locator('nav a[data-page="queue"]').click()
                expect(page.locator('#live-queue .patient-name')).to_have_text(['Morgan Fictional','Sky Fictional','Avery Fictional'])
                page.locator('#queue-active [data-action="next"]').click(); page.locator('#confirm-action').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                expect(page.locator('#queue-active')).to_contain_text('Morgan Fictional')
                page.locator('#queue-active [data-action="complete"]').click(); page.locator('#confirm-action').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                page.locator('[data-action="undo"]').click(); page.locator('#confirm-action').click()
                expect(page.locator('#confirm-dialog')).not_to_be_visible()
                expect(page.locator('#live-queue .patient-name')).to_have_text(['Avery Fictional'])
                page.locator('nav a[data-page="patients"]').click()
                page.locator('#search-kind').select_option('find_name'); page.locator('#search-term').fill('Sky Fictional')
                page.locator('#search-form button[type=submit]').click()
                expect(page.locator('#patients-table tbody tr')).to_have_count(1)
                expect(page.locator('#patients-table')).to_contain_text('Registered')
                expect(page.locator('#patients-table')).to_contain_text('2 · Urgent')
                page.locator('#patients-table [data-history]').click()
                expect(page.locator('#visit-content')).to_contain_text('No visits recorded yet')
                page.locator('#visit-dialog [data-close]').click()
                page.locator('nav a[data-page="history"]').click()
                expect(page.locator('#history-table')).to_contain_text('Morgan Fictional')
                expect(page.locator('#history-table')).to_contain_text('Completed')
                page.locator('nav a[data-page="reports"]').click()
                for algorithm in ['1','2']:
                    page.locator('#report-algorithm').select_option(algorithm)
                    page.locator('#report-key').select_option('2')
                    page.locator('#report-form button[type=submit]').click()
                    expect(page.locator('#report-table .patient-name')).to_have_text(['Morgan Fictional','Sky Fictional','Avery Fictional'])
                page.locator('nav a[data-page="storage"]').click()
                expect(page.locator('#storage-details')).to_contain_text('Autosave')
                page.locator('[data-action="save"]').click()
                expect(page.locator('#toast')).to_have_text('Snapshot saved')
                page.reload()
                page.locator('#staff-pin').fill(server.staff_pin); page.locator('#staff-login-form button').click()
                expect(page.locator('#connection')).to_have_text('Local engine connected')
                assert not errors, errors
                browser.close()
                print('PASS: browser registration, severity validation, responsive layout, C queue order, consultation, undo, search, history, both reports, save and page reload; no JavaScript errors')
                print('Screenshots: build/screenshots/dashboard-desktop.png and dashboard-mobile.png')
        finally:
            server.shutdown(); thread.join(timeout=5); server.server_close(); server.engine.close()

if __name__ == '__main__':
    main()
