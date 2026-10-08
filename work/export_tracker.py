# -*- coding: utf-8 -*-
"""
待核价清单导出：data/scored.json -> outputs/site/checklist.xlsx
================================================================
把「冷门优选 + 盯款雷达」导出成和「选品追踪表 · 试销追踪」同格式的 Excel，
自动填好货源价/费率/公式，用户每天只需要：App核价(E列) -> 买1-2件 -> 卖出后补 I列。
页面顶部提供下载入口；账单先验同理，这张表是「线报站 -> 追踪表」的回路A。

用法:
  python work/export_tracker.py                 # 全量导出（冷门优选+可蹲，上限15条）
  python work/export_tracker.py --max 10 --out 自定义路径.xlsx
"""
import argparse
import json
import os
from datetime import datetime, timezone, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORED = os.path.join(ROOT, "data", "scored.json")
SITE_OUT = os.path.join(ROOT, "outputs", "site", "checklist.xlsx")
BEIJING = timezone(timedelta(hours=8))

BLUE = "1F4E79"
ALT = "F7F9FB"
LINE = "E3E6EA"

HEADERS = ["候选品", "试销日期", "货源价(元)", "得物核价(元)", "核价后价差率", "试销件数",
           "已卖出件数", "卖出均价(元)", "平台费率", "快递费(元/件)", "单均净利(元)",
           "满3单？", "加仓决策", "得物价参考", "参考净利(元)", "标签", "门道链接"]
ORDER = {"冷门优选": 0, "可蹲·降价中": 1, "可蹲": 2}


def pick(scored, max_rows):
    """冷门优先 -> 降价中 -> 可蹲，各标签内按稀缺分降序。"""
    items = [x for x in scored if x.get("verdict") in ORDER]
    items.sort(key=lambda x: (ORDER[x["verdict"]], -(x.get("scarcity_score") or 0)))
    return items[:max_rows]


def build(items, path, stamp):
    wb = Workbook()
    ws = wb.active
    ws.title = "试销追踪"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    last_col = 1 + len(HEADERS)  # B 起

    ws.merge_cells(start_row=2, start_column=2, end_row=2, end_column=last_col)
    c = ws.cell(row=2, column=2, value=f"待核价清单（{stamp} 生成 · 线报站自动导出）")
    c.font = Font(size=14, bold=True, color=BLUE)
    ws.row_dimensions[2].height = 28

    fill = PatternFill("solid", fgColor=BLUE)
    for i, h in enumerate(HEADERS, start=2):
        hc = ws.cell(row=4, column=i, value=h)
        hc.fill = fill
        hc.font = Font(size=11, bold=True, color="FFFFFF")
        hc.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[4].height = 28
    for col, w in [("B", 34), ("C", 12), ("D", 11), ("E", 11), ("F", 12), ("G", 9), ("H", 10),
                   ("I", 12), ("J", 10), ("K", 12), ("L", 12), ("M", 9), ("N", 10),
                   ("O", 12), ("P", 12), ("Q", 12), ("R", 40)]:
        ws.column_dimensions[col].width = w

    for idx, it in enumerate(items):
        r = 5 + idx
        row_fill = PatternFill("solid", fgColor="FFFFFF" if idx % 2 == 0 else ALT)
        tr = it.get("price_trend") or {}
        trend_txt = ""
        if tr:
            trend_txt = f"¥{tr.get('first')}→¥{tr.get('last')} ({tr.get('pct'):+}%)"
        values = {
            "B": it.get("title"),
            "D": it.get("cost"),
            "J": 0.05,
            "K": 3,
            "O": it.get("du_price"),
            "P": it.get("net_profit"),
            "Q": it.get("verdict") + (f"·{trend_txt}" if trend_txt else ""),
            "R": it.get("url"),
        }
        formulas = {
            "F": f'=IFERROR(IF(OR(D{r}="",E{r}=""),"",(E{r}-D{r})/D{r}),"")',
            "L": f'=IF(OR(D{r}="",I{r}=""),"",I{r}*(1-J{r})-D{r}-K{r})',
            "M": f'=IF(H{r}="","",IF(H{r}>=3,"是","否"))',
            "N": f'=IF(OR(D{r}="",E{r}=""),"",IF(F{r}<0.15,"放弃",IF(AND(H{r}>=3,L{r}>=25),"加仓","观察")))',
        }
        for col_letter in "BCDEFGHIJKLMNOPQR":
            cell = ws[f"{col_letter}{r}"]
            if col_letter in values:
                cell.value = values[col_letter]
            elif col_letter in formulas:
                cell.value = formulas[col_letter]
            cell.fill = row_fill
            cell.font = Font(size=11, color="37352F")
            cell.alignment = Alignment(
                horizontal="left" if col_letter in ("B", "Q", "R") else "right",
                vertical="center", wrap_text=col_letter in ("B", "Q", "R"))
        ws[f"J{r}"].number_format = "0.0%"
        ws[f"F{r}"].number_format = "0.0%"
        for col_letter in ("D", "E", "I", "K", "L", "O", "P"):
            ws[f"{col_letter}{r}"].number_format = "#,##0.00"
        ws.row_dimensions[r].height = 22

    note_row = 5 + len(items) + 1
    ws.merge_cells(start_row=note_row, start_column=2, end_row=note_row, end_column=last_col)
    nc = ws.cell(row=note_row, column=2,
                 value="用法：得物App核价填E列 -> 买1-2件 -> 卖出后补G/H/I列；「加仓」条件=价差率≥15%且满3单且单均净利≥25元，公式自动判定。"
                       "D列货源价来自门道到手价，下单前自行复核。")
    nc.font = Font(size=9, color="8C8A84")
    nc.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[note_row].height = 30

    ws.freeze_panes = "C5"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)
    print("OK:", path, os.path.getsize(path), "bytes,", len(items), "rows")


def main():
    ap = argparse.ArgumentParser(description="待核价清单导出")
    ap.add_argument("--max", type=int, default=15)
    ap.add_argument("--out", default=SITE_OUT, help="输出路径（默认 outputs/site/checklist.xlsx）")
    args = ap.parse_args()

    scored = json.load(open(SCORED, encoding="utf-8")) if os.path.exists(SCORED) else []
    items = pick(scored, args.max)
    stamp = datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")
    build(items, SITE_OUT, stamp)
    if os.path.abspath(args.out) != os.path.abspath(SITE_OUT):
        build(items, args.out, stamp)


if __name__ == "__main__":
    main()
