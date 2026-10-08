# 得物搬砖 · 差异化线报 v2

自动盯「门道商机」（得物官方搬砖工具），按稀缺分筛选，每天两次自动更新到 GitHub Pages。

**线上地址**：https://aa563977885-web.github.io/rixianbao/

## 页面怎么用
- **📋 今日机会**：新发现、没被全网抢烂的款（稀缺分降序，⭐冷门优选置顶）
- **👀 盯款雷达**：被抢烂但仍在售、仍有净利的款——等降价，蹲到心理价再入
- **🚫 避坑区 / ⏰ 过期归档**：折叠收起，不碍眼
- **📥 待核价清单**：页顶下载 checklist.xlsx，冷门优选+可蹲已按「选品追踪表」格式导出，填 App 核价两列即可试销

策略与公式详见 [DIFF_STRATEGY.md](DIFF_STRATEGY.md)。

## 本地运行
```bash
pip install -r requirements.txt
python crawl_mendao.py --seed <carryId> --depth 2   # 爬取（Actions 里自动跑）
python work/scoring.py                              # 打分
python work/make_html.py                            # 渲染到 outputs/
python work/ledger_prior.py --bill "得物 账单.xlsx"  # 账单回流：用真实成交数据校准类目分
python work/export_tracker.py                       # 回路A：导出待核价清单 -> outputs/site/checklist.xlsx
python work/test_scoring.py                         # 单测
```

## 配置
- `config/rates.json`：费率、目标净利、冷门优选阈值
- `config/tiers.json`：类目冷热门
- `config/ledger_prior.json`：个人账单先验（ledger_prior.py 生成，勿手改）

## 推送（可选）
仓库 Secrets 配置 `SEED_ID`（必填）、`SERVERCHAN_SENDKEY` 或 `BARK_KEY`（选填）。
推送为**每日晨报**：新冷门优选 + 盯款雷达降价 + 全局统计，一条微信看完。
