"""Refresh registered products through public App links and visible UI, without search.

No private API, app storage, credentials, listing submission or background schedule.
The anonymous sell icon is limited to the observed 5.83.0 / 1920x1080 layout.
"""
import argparse
import json
import math
import re
import shlex
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

PACKAGE = 'com.shizhuang.duapp'
PREFIX = PACKAGE + ':id/'
SELL_BOUNDS = '[731,51][790,110]'
PROFILE_VERSION = '5.83.0'


def product_url(product):
    for field in ('article_no', 'color', 'gender'):
        if not isinstance(product.get(field), str) or not product[field].strip():
            raise ValueError('Missing product identity')
    query = {}
    for field, parameter in [('spu_id', 'spuId'), ('property_value_id', 'propertyValueId'), ('sku_id', 'skuId')]:
        value = product.get(field)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
            raise ValueError('Invalid public product ID')
        query[parameter] = value
    public = urlsplit(product['public_url'])
    if (public.scheme != 'https' or public.netloc != 'www.dewu.com'
            or public.path != '/product-detail.html'
            or any(parse_qs(public.query).get(k) != [v] for k, v in query.items())):
        raise ValueError('Product IDs do not match the public share landing page')
    if product.get('app_version') != PROFILE_VERSION:
        raise ValueError('Unverified App layout version')
    return 'https://m.dewu.com/router/product/ProductDetail?' + urlencode(query)


def value(root, suffix):
    return next((n.get('text', '') for n in root.iter('node')
                 if n.get('resource-id') == PREFIX + suffix), '')


def has_identity(root, product, panel=False):
    if any(n.get('package') not in ('', None, PACKAGE) for n in root.iter('node')):
        return False
    if panel:
        title = value(root, 'tvPropName')
        return (value(root, 'tvArticleNumber') == '货号：' + product['article_no']
                and product['gender'] + ' ' + product['color'] in title)
    return (any(n.get('text') == product['article_no'] for n in root.iter('node'))
            and any(product['gender'] + ' ' + product['color'] in n.get('text', '') for n in root.iter('node')))


def selected_channel(root):
    return any(n.get('text') == '普通发货' and n.get('selected') == 'true' for n in root.iter('node'))


def extract_income(root, product):
    if not has_identity(root, product, panel=True) or not selected_channel(root):
        raise ValueError('Income panel identity or ordinary-delivery channel mismatch')
    tabs = [n for n in root.iter('node') if n.get('resource-id') == PREFIX + 'itemIncome']
    if len(tabs) != 1 or tabs[0].get('selected') != 'true':
        raise ValueError('Estimated-income tab is not selected')
    if not any(n.get('resource-id') == PREFIX + 'tvName' and n.get('text') == product['color']
               and n.get('selected') == 'true' for n in root.iter('node')):
        raise ValueError('Selected color mismatch')
    parents = {child: parent for parent in root.iter() for child in parent}
    rows, seen = [], set()
    for n in root.iter('node'):
        size = n.get('text', '')
        if n.get('resource-id') != PREFIX + 'tvName' or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', size):
            continue
        price = value(parents[n], 'tvPrice')
        if not re.fullmatch(r'[¥￥][0-9]+(?:\.[0-9]+)?', price) or size in seen:
            raise ValueError('Ambiguous or invalid visible income row')
        amount = float(price[1:])
        if not math.isfinite(amount):
            raise ValueError('Non-finite income')
        seen.add(size)
        rows.append({'size': size, 'estimated_income': amount})
    if not rows:
        raise ValueError('No visible income rows')
    return rows


class AndroidUI:
    def __init__(self, adb_path, device):
        self.adb_path, self.device = adb_path, device
        self.remote = '/sdcard/rixianbao-direct-' + uuid.uuid4().hex + '.xml'

    def run(self, *args):
        result = subprocess.run([self.adb_path, '-s', self.device, *args],
                                capture_output=True, timeout=30, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError('Android command failed: ' + result.stderr.strip()[:200])
        return result.stdout

    def snapshot(self):
        self.run('shell', 'rm', '-f', self.remote)
        try:
            dumped = self.run('shell', 'uiautomator', 'dump', self.remote)
            if 'dumped to:' not in dumped:
                raise RuntimeError('No fresh UI dump')
            return ET.fromstring(self.run('shell', 'cat', self.remote))
        finally:
            self.run('shell', 'rm', '-f', self.remote)

    def wait_for(self, predicate):
        for _ in range(3):
            time.sleep(1)
            try:
                root = self.snapshot()
            except (RuntimeError, ET.ParseError, subprocess.TimeoutExpired):
                continue
            if predicate(root):
                return root
        raise RuntimeError('Expected public product page not available; snapshot was not updated')

    def tap(self, node):
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if not bounds:
            raise ValueError('Invalid observed button bounds')
        x1, y1, x2, y2 = map(int, bounds.groups())
        self.run('shell', 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))

    def screenshot(self, path):
        remote = self.remote.replace('.xml', '.png')
        try:
            self.run('shell', 'screencap', '-p', remote)
            self.run('pull', remote, str(path))
        finally:
            self.run('shell', 'rm', '-f', remote)


def refresh(ui, product):
    url = product_url(product)
    package_info = ui.run('shell', 'dumpsys', 'package', PACKAGE)
    version = re.search(r'\bversionName=([^\s]+)', package_info)
    if not version or version[1] != PROFILE_VERSION:
        raise RuntimeError('App version changed; the sell-icon layout needs review')
    result = ui.run('shell', 'am start -W -a android.intent.action.VIEW -d '
                    + shlex.quote(url) + ' -p ' + PACKAGE)
    if 'Error:' in result or 'Status: ok' not in result:
        raise RuntimeError('Public product link could not open the App')
    root = ui.wait_for(lambda r: has_identity(r, product))
    if not any(n.get('bounds') == '[0,0][1920,1080]' for n in root.iter('node')):
        raise RuntimeError('Unverified screen size')
    buttons = [n for n in root.iter('node') if n.get('clickable') == 'true'
               and n.get('bounds') == SELL_BOUNDS and n.get('resource-id') == '']
    if len(buttons) != 1:
        raise RuntimeError('Observed sell-entry layout changed')
    ui.tap(buttons[0])
    root = ui.wait_for(lambda r: has_identity(r, product, panel=True))
    if not selected_channel(root):
        channels = [n for n in root.iter('node') if n.get('text') == '普通发货' and n.get('clickable') == 'true']
        if len(channels) != 1:
            raise RuntimeError('Ordinary-delivery channel unavailable')
        ui.tap(channels[0])
        root = ui.wait_for(lambda r: has_identity(r, product, panel=True) and selected_channel(r))
    tabs = [n for n in root.iter('node') if n.get('resource-id') == PREFIX + 'itemIncome']
    if len(tabs) != 1 or tabs[0].get('clickable') != 'true':
        raise RuntimeError('Estimated-income tab unavailable')
    if tabs[0].get('selected') != 'true':
        ui.tap(tabs[0])
    root = ui.wait_for(lambda r: has_identity(r, product, panel=True)
                       and any(n.get('resource-id') == PREFIX + 'itemIncome' and n.get('selected') == 'true'
                               for n in r.iter('node')))
    rows = extract_income(root, product)
    return {'article_no': product['article_no'], 'color': product['color'], 'gender': product['gender'],
            'spu_id': product['spu_id'], 'public_url': product['public_url'], 'direct_url': url,
            'captured_at': datetime.now().astimezone().isoformat(), 'kind': 'income',
            'price_kind': 'app_estimated_income', 'income_channel': '普通发货', 'tab_verified': True,
            'channel_verified': True, 'records': rows, 'source': 'Dewu Android visible UI via public product link',
            'navigation': 'direct_product_link_without_search', 'coverage': 'visible_sizes_only',
            'seller_settlement': None, 'net_profit': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--device', default='emulator-5554')
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--article', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--evidence')
    args = parser.parse_args()
    products = json.loads(Path(args.catalog).read_text(encoding='utf-8'))
    matches = [p for p in products if p.get('article_no') == args.article]
    if len(matches) != 1:
        raise ValueError('Register one unambiguous verified product before refreshing')
    ui = AndroidUI(args.adb, args.device)
    result = refresh(ui, matches[0])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.evidence:
        evidence = Path(args.evidence)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        ui.screenshot(evidence)
        result['evidence'] = [evidence.name]
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(output)
    print(json.dumps({'article_no': result['article_no'], 'navigation': result['navigation'],
                      'captured_at': result['captured_at'], 'visible_sizes': len(result['records']),
                      'records': result['records']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
