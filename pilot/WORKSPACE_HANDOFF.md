# P4：新工作区接手说明

## 先读这些

- `pilot/runs/p4/v7_c2_step2_delegation_20261007/report.md`：操作委托失败机制及15个确认案例。
- `pilot/runs/p4/v7_c2_native912_20261007/report.md`：912条原生运行的离线普查。
- `pilot/runs/p4/v7_c3_cost_control_20261008/report.md`：成本改造、预算与OpenRouter失败记录。
- `pilot/runs/p4/v7_c4_relay_20261009/report.md`：最新中转接入及三个小接口测试。
- `pilot/runs/p4/v7_c2_report_20261006_r2/search.py`：A0–A4搜索比较实现。

## 当前结论与待完成任务

已经独立验证了固定伙伴回复的有害/有益效应，归纳出“用户要求agent执行只有用户可做的手机操作，agent以缺少工具为由转人工”的交互机制。912条原生轨迹中678条失败，17条包含明确测速委托后立即转人工，均失败；占失败2.5%，移动数据失败7.5%。这是观测路径比例，不是完成干预验证后的因果归因比例。

优先任务仍是完成搜索循环与baseline的等预算比较；不能将当前不完整批次宣布为方法效率优势。机制措辞配对与prompt修复计划位于 `pilot/runs/p4/v7_c2_mechanism_intervention_plan_20261007/plan.json`，尚未执行。

## 当前调用状态与预算

实验agent/partner仍为历史实际使用的gpt-5.6-luna，温度1；Sol用于判官和必要的强agent对照。不得用新模型别名替换后混入旧批次。

本次授权Sol累计最多$20。此前OpenRouter的Sol失败请求保留$0.047712未知费用预留，所以新中转账本的Sol可用限额为$19.952288；不是确认扣款。附加总模型费用上限$40，沿用每臂限额与完整复测次数，不因节省成本减少复测。新提供商费率尚未获得，不能沿用OpenRouter费率。

OpenRouter对Luna/Sol生成返回地区403。新中转 `https://api.vvvcode.com/v1/responses` 认证及Luna生成成功；显式instructions能保留原生提示，工具调用成功。但请求温度0返回1，max_output_tokens=16时输出70tokens，故正式搜索和判官验证尚未启动。三个Luna接口测试共4605tokens，零Sol调用。

新接入只在P4实验进程使用，不改 `~/.codex/config.toml`、`auth.json`、shell启动文件或当前订阅配置。持续两次401停止，不循环重试。停止标记保留，不能只删除标记后强行跑；先确认服务正确传递温度/输出上限及实际价格，再复测并记录修正。

## 安装与离线核对

在仓库根目录：

```bash
uv sync --extra dev
PYTHONPATH=pilot:pilot/runs/p4/v7_c2_report_20261006_r2:pilot/runs/p4/v7_c2_step1_20261006_r2 uv run python -m unittest pilot/test_p4_responses_transport.py pilot/test_p4_cost_control.py pilot/runs/p4/v7_c2_report_20261006_r2/test_revision.py
make check-all
```

交接时33项测试与全仓lint/format通过。离线测试不需要API key。

独立新入口（当前应在模型调用前因协议停止标记而停止）：

```bash
P4_RUN_ROOT=pilot/runs/p4/v7_c4_relay_20261009 uv run python pilot/p4_cost_control_run.py --run --arm A0
```

## Git与原始数据

项目远端：`https://github.com/mianwu01/Agent.git`；研究分支：`research/p4-v7-20261008`。Sierra仓库保留为上游。Git包含代码、报告、计划、结果摘要和个案卡片；密钥、SQLite账本、原始请求/续写/完整轨迹不入库。

完整原始数据仍在：

`/mnt/dolphinfs/ssd_pool/docker/user/hadoop-nlp-hl02/hadoop-aipnlp/3A/multimodal/yangboxue/tts-sft/external/agent/pilot/runs/`

重算历史实验或恢复旧批次前，必须从该位置复制整个 `pilot/runs/`；特别是 `pilot/runs/iid/default/results.json`（912条原生轨迹）与各批次requests/continuations/trajectories/sources。Git摘要不是完整原始数据备份。`pilot/GIT_SNAPSHOT_20261008.json`列出旧快照包含文件的哈希和原始目录排除索引。

若在同一机器的新目录，可以直接复制：

```bash
rsync -a /mnt/dolphinfs/ssd_pool/docker/user/hadoop-nlp-hl02/hadoop-aipnlp/3A/multimodal/yangboxue/tts-sft/external/agent/pilot/runs/ ./pilot/runs/
```

不同机器使用有权读取上述目录的SSH/文件传输方式。SQLite费用账本随原始数据一起复制，保留已有预留及失败停止标记。旧账本配置不能更换单价后继续复用；新提供商使用独立目录及账本，并扣除之前授权范围内的预留。

API凭据不在Git。新工作区通过各自私有凭据文件配置；不要复制或覆盖订阅Codex的认证文件。此任务没有新增实验采样。
