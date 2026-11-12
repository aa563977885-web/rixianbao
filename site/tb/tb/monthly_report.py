# -*- coding: utf-8 -*-
"""得物搬砖月度账单分析器
用法: python monthly_report.py "C:\\path\\to\\账单.xlsx" [输出目录]
固定分析模板: 月度P&L / 资金周转 / 利润率分布 / 滞销预警 / 加仓清仓观察三档清单
"""
import sys, os, datetime
import openpyxl
import sys as _s
try: _s.stdout.reconfigure(encoding='utf-8')
except Exception: pass
from collections import defaultdict

TODAY = datetime.date.today()
CATS = ('鞋子', '衣服', '美妆', '帽子', '包包')

def parse_date(v):
    if v is None: return None
    if isinstance(v, datetime.datetime): return v.date()
    if isinstance(v, datetime.date): return v
    try: return datetime.datetime.strptime(str(v)[:10], '%Y/%m/%d').date()
    except Exception:
        try: return datetime.datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
        except Exception: return None

def fnum(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

def analyze(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    rep = []

    # ============ 一、账单详情:月度P&L + 月度利润曲线 ============
    if '账单详情' in wb.sheetnames:
        ws = wb['账单详情']
        mon_cap = defaultdict(float); mon_profit = defaultdict(float)
        total_buy = total_profit = 0.0; n = 0
        for r in range(2, ws.max_row + 1):
            name = ws.cell(row=r, column=1).value
            if not name: continue
            buy = fnum(ws.cell(row=r, column=3).value) * (fnum(ws.cell(row=r, column=4).value) or 1)
            profit = fnum(ws.cell(row=r, column=7).value)
            pay = str(ws.cell(row=r, column=9).value or '')[:7]
            mon = str(ws.cell(row=r, column=11).value or '')[:7]
            total_buy += buy; total_profit += profit; n += 1
            if mon: mon_cap[mon] += buy
            if pay: mon_profit[pay] += profit
        rep.append('═' * 20 + ' 月度损益曲线 ' + '═' * 20)
        months = sorted(set(list(mon_cap) + list(mon_profit)))
        for m in months:
            cap = mon_cap.get(m, 0); pf = mon_profit.get(m, 0)
            rate = f'{pf/cap*100:.1f}%' if cap else '-'
            rep.append(f'  {m}: 投入 {cap:>8.0f} | 利润 {pf:>7.0f} | 月化 {rate}')
        rep.append(f'  合计: 投入 {total_buy:.0f} | 总利润 {total_profit:.0f} | 订单 {n} 单\n')

    # ============ 二、货架表:滞销/加仓/清仓/观察 ============
    shelf_name = None
    for sn in wb.sheetnames:
        if '十月' in sn or '双十一' in sn or '货架' in sn:
            shelf_name = sn; break
    if shelf_name:
        ws = wb[shelf_name]
        items = []
        cur = '?'
        for r in range(2, ws.max_row + 1):
            c1 = ws.cell(row=r, column=1).value
            if c1 and str(c1).strip() in CATS: cur = str(c1).strip()
            name = ws.cell(row=r, column=2).value
            if not name: continue
            items.append(dict(
                cat=cur, name=str(name)[:30], code=str(ws.cell(row=r, column=3).value or '')[:14],
                buy=fnum(ws.cell(row=r, column=4).value), qty=int(fnum(ws.cell(row=r, column=5).value) or 1),
                sell=fnum(ws.cell(row=r, column=6).value), profit=fnum(ws.cell(row=r, column=8).value),
                margin=fnum(ws.cell(row=r, column=9).value), recv=parse_date(ws.cell(row=r, column=10).value),
            ))
        sold = [x for x in items if x['sell'] > 0]
        unsold = [x for x in items if x['sell'] == 0]
        rep.append('═' * 20 + ' 货架总览 ' + '═' * 20)
        rep.append(f'  总SKU {len(items)} | 已售 {len(sold)} | 在架 {len(unsold)}')
        rep.append(f'  买入合计 {sum(x["buy"]*x["qty"] for x in items):.0f} | 在架占用 {sum(x["buy"]*x["qty"] for x in unsold):.0f}')
        rep.append(f'  已售净利合计 {sum(x["profit"] for x in sold):.0f}\n')

        # 加仓/清仓/观察 三档（只统计已售≥1次的SKU款式聚合）
        agg = defaultdict(lambda: dict(sold_n=0, profit=0.0, margin=[], cat='', recv=[]))
        for x in sold:
            k = x['name'][:20]
            a = agg[k]
            a['sold_n'] += 1; a['profit'] += x['profit'] or 0
            if x['margin']: a['margin'].append(x['margin'])
            a['cat'] = x['cat']
            if x.get('recv'): a['recv'].append(x['recv'])
        restock, watch, purge = [], [], []
        for k, a in agg.items():
            avg_m = sum(a['margin'])/len(a['margin']) if a['margin'] else 0
            if a['sold_n'] >= 2 and avg_m >= 0.20: restock.append((k, a, avg_m))
            elif avg_m < 0.10: purge.append((k, a, avg_m))
            else: watch.append((k, a, avg_m))
        rep.append('═' * 16 + ' 加仓清单（售≥2次且净利率≥20%）' + '═' * 14)
        for k, a, m in sorted(restock, key=lambda x: -x[1]['profit']):
            rep.append(f'  ✔ {k} | 售{a["sold_n"]}次 净利{a["profit"]:.0f} 平均净利率{m*100:.0f}%')
        if not restock: rep.append('  （暂无——需更多售出记录积累数据）')
        rep.append('')
        rep.append('═' * 16 + ' 观察清单 ' + '═' * 30)
        for k, a, m in sorted(watch, key=lambda x: -x[1]['profit']):
            rep.append(f'  ○ {k} | 售{a["sold_n"]}次 净利{a["profit"]:.0f} 平均净利率{m*100:.0f}%')
        if not watch: rep.append('  （暂无）')
        rep.append('')
        rep.append('═' * 16 + ' 清仓清单（净利率<10%）' + '═' * 26)
        for k, a, m in sorted(purge, key=lambda x: x[1]['profit']):
            rep.append(f'  ✂ {k} | 售{a["sold_n"]}次 净利{a["profit"]:.0f} 平均净利率{m*100:.0f}%')
        if not purge: rep.append('  （暂无——很好）')

        # 在架滞销预警
        rep.append('')
        rep.append('═' * 16 + ' 滞销预警（在架未售，按收货天数）' + '═' * 12)
        warn = [( (TODAY - x['recv']).days if x['recv'] else -1, x) for x in unsold]
        w30 = [x for d, x in warn if d >= 30]; w45 = [x for d, x in warn if d >= 45]
        rep.append(f'  在架≥30天: {len(w30)}件 占资 {sum(x["buy"]*x["qty"] for x in w30):.0f}')
        rep.append(f'  在架≥45天: {len(w45)}件 占资 {sum(x["buy"]*x["qty"] for x in w45):.0f} ←优先清仓')
        for d, x in sorted(warn, key=lambda p: -p[0])[:10]:
            if d >= 30: rep.append(f'    {d}天 [{x["cat"]}] {x["name"]} ¥{x["buy"]*x["qty"]:.0f}')
    return '\n'.join(rep)

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\Windows\Downloads\得物 账单 (1).xlsx'
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(path), '月度报告')
    os.makedirs(outdir, exist_ok=True)
    report = analyze(path)
    fname = os.path.join(outdir, f'月度分析_{TODAY:%Y%m%d}.md')
    open(fname, 'w', encoding='utf-8').write(report)
    print(report)
    try:
        import sys as _sys
        _sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(f'\n报告已保存: {fname}')
