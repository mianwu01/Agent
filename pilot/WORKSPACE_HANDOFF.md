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

## 2026-10-09/10 更新：OpenRouter 新模型与方法 v2（Windows 工作区）

报告：
- `pilot/runs/p4/v7_c5_openrouter_us_20261009/`：模型筛选、判官筛选、原生基线（`native/report.md`、`native_minimax/report.md`）。
- `pilot/runs/p4/v7_c6_openrouter_search_20261009/report.md`：首轮 A0/A3（试运行，不能比较方法）。
- `pilot/runs/p4/v7_c7_method_v2_20261009/`：方法 v2 A0/A3，`plan_amendment_method_v2.json`、`task_selection.json`。

模型（OpenRouter，单一供应商、关闭 reasoning）：OpenAI 自营模型对该账号返回 403“previous policy violation”（含 Luna/Sol/GPT-4.1）。替代：Luna 角色 → `deepseek/deepseek-v4.1-flash`（Fireworks，温度1）；Sol 角色（判官温度0、强 agent）→ `moonshotai/kimi-k3`（InferenceNet）；other family → `qwen/qwen3.8-flash`（Alibaba）。映射见 `model_mapping.json`、`provider_config.json`。账号隐私设置会过滤 DeepSeek 自营端点。

关键结论：
- DeepSeek 原生 81% 通过（Luna 26%）；Luna 的“委托设备操作→立即转人工”机制在 DeepSeek 和 MiniMax 上均不存在（agent 会指导用户自行操作）。
- 冻结的 20 个种子任务对 DeepSeek 太容易；v2 改用 20 个原生通过率约 44% 的任务（主要 mms）。
- v2：美元预算（每臂 $25，阶段比例不变）、零位移不复测、筛选期原生回合只做程序检查（判官费用约降 80%）。
- v2 A3 完成：9 次扩展集中在同一任务（方差探索项太小），4 次复测全部不显著（筛选每候选只 2 次续写，赢家诅咒）。0 个验证案例。
- v2 A0 在复测阶段暂停（约 $10，19 次扩展，覆盖 5 个任务），可续跑：
  `cd pilot && PYTHONUTF8=1 P4_RUN_ROOT=$PWD/runs/p4/v7_c7_method_v2_20261009 P4_ARM_BUDGET_USD=25 P4_RETEST_MIN_SHIFT=0.01 P4_JUDGE_BRANCH_ONLY=1 python p4_cost_control_run.py --run --arm A0 --workers 10`
  续跑需要本机原始数据（未入库），否则应在 v3 中重跑。

运行稳健性修复（均写在 amendment 中）：30 次拒绝后仅放宽 STOP 规则；无法采样的状态跳过；429/网络/SSL 退避重试；续跑时归档未完成后缀的伙伴回合，防止拼接；严格回放不一致时保存前缀并跳过。

下一步（建议）：用已有数据离线分析筛选位移对复测的预测力 → 正对照（植入已知有害回复验证检测力）→ 方法 v3（筛选加大样本/收缩排序、复测序贯早停、A3 加大探索并限制同节点次数）→ v3 A0 vs A3 各约 $25。

费用：本日 OpenRouter 约 $88，key 剩余约 $422。网络：所有调用每轮重发完整对话，约 715M 输入 token ≈ 3–3.5GB 上传；应在服务器或低倍率节点上运行，勿走家宽节点。

Git 不含：原始回复/轨迹/成本账本/日志/shadow 输入/完整 results.json（约 4GB），仅在本机 `C:\Users\Merlin\Desktop\111\Agent\pilot\runs\p4\v7_c5..c7`。
