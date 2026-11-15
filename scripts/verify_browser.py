"""Check the English UI and approve the pending runtime-verification case.

Run after verify_runtime.py --with-model, using a Python Playwright environment.
Only the exact case ID recorded in reports/verification.json is reviewed.
"""
import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--browser-path')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
report_path = root / 'reports/verification.json'
report = json.loads(report_path.read_text())
artifacts = root / 'artifacts'
artifacts.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, **({'executable_path': args.browser_path} if args.browser_path else {}))
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8780')
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('heading', name='Follow a record. Check every handoff.')).to_be_visible()
    expect(page.locator('#connections .good')).to_have_count(2)
    expect(page.locator('#notice')).to_be_empty()
    page.get_by_role('button', name='Load billing example', exact=True).click()
    expect(page.locator('#notice')).to_contain_text('Imported successfully', timeout=15000)
    expect(page.locator('#comparison .metric strong')).to_have_text(['7', '7', 'Match'])
    page.screenshot(path=str(artifacts / 'desktop.png'), full_page=True)

    live_key = report['sources']['live']['patient']['patient_key']
    page.locator('#patient').select_option(live_key)
    expect(page.locator('#comparison .metric strong')).to_have_text(['24', '24', 'Match'])
    case = next(c for c in report['cases'] if c['source'] == 'live')
    button = page.locator(f'button[data-id="{case["id"]}"][data-decision="approve"]')
    expect(button).to_be_visible()
    article = button.locator('xpath=ancestor::article')
    expect(article.locator('.pending')).to_contain_text('No reply published')
    draft = article.locator('textarea').input_value()
    button.click()
    expect(page.locator('#cases .reply')).to_contain_text(draft, timeout=10000)
    # Reload from SQL Server: DOM transition alone is not persistence evidence.
    page.reload(); page.wait_for_load_state('networkidle')
    page.locator('#patient').select_option(live_key)
    expect(page.locator('#cases .reply')).to_contain_text(draft)
    case['status'] = 'approved_via_browser'

    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(artifacts / 'mobile.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
    assert not re.search(r'[\u4e00-\u9fff]', page.locator('body').inner_text()), 'Unexpected Chinese UI text'
    assert not errors, errors
    browser.close()

report['browser_checks'] = {'desktop_1440': True, 'mobile_390': True, 'no_horizontal_overflow': True,
    'english_ui': True, 'page_errors': errors, 'fixture_reimport_via_ui': True,
    'approval_persisted_after_reload': True}
report_path.write_text(json.dumps(report, indent=2) + '\n')
print('Desktop/mobile, English UI, reimport, and persisted review checks passed.')
