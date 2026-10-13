# 自己的线报 · 联盟独立选品

京东、淘宝联盟发现候选，得物按同货号、颜色和规格独立核价，再估算利润。每日工作流和本机更新已取消对门道爬虫、门道快照和门道款式供体的调用。

未核价商品只展示联盟参考价；缺少有效货源链接、报价超过24小时、货源成本变化或规格不匹配，都会回到待核价。当前自动批量查得物价尚未接通，需人工核价。

核价格式、费用口径及操作步骤见 [INDEPENDENT.md](INDEPENDENT.md)。

```text
python work/source_allies.py
python work/independent.py
python work/scoring.py
python work/export_tracker.py
python work/make_html.py
```

联盟密钥使用既有 Actions Secrets：TBK_APPKEY、TBK_APPSECRET、JD_UNION_APPKEY、JD_UNION_APPSECRET。无需 SEED_ID。

```text
python -m unittest discover -s work -p "test_*.py"
```

旧门道脚本和快照保留为历史资料，独立页面不使用其价格或候选。
