# P4 v7 中转接入检查 — 2026-10-09

独立接入 `https://api.vvvcode.com/v1/responses`；未安装或重配 Codex CLI。当前订阅的 `~/.codex/config.toml` 和 `auth.json` 在接入前后 SHA-256 一致。凭据只在项目内的私有文件中保存，权限 0600，Git 排除；不写入 shell 启动文件或全局 OPENAI_API_KEY。

## 接口结果

模型列表返回 200，含原实验的 gpt-5.6-luna 与 gpt-5.6-sol。仅执行三个 Luna 小接口测试，全部 HTTP 200，零 Sol 调用、零实验续写。

|检查|请求|实际结果|
|---|---|---|
|默认提示|未传 instructions；输出上限32|自动添加21,334字节 Codex提示，提示归因4,380 tokens；输出5 tokens，上限回显null|
|显式提示与用户工具|原文117字节 instructions；强制 read_device_status(network_mode)|提示原文一致；工具名与参数正确；输入81、输出20 tokens|
|判官温度与输出上限|temperature=0；max_output_tokens=16；JSON格式|返回 temperature=1；输出70 tokens；上限回显null；JSON格式保留|

三个测试合计输入4,510、输出95、总计4,605 tokens，其中缓存输入3,840。当前没有该提供商的实际费率，费用未核实，不用 OpenRouter 单价估算成实际扣款。已有授权账本中的 Sol 未知费用预留 $0.047712 保留，新账本 Sol 剩余限额 $19.952288；这些接口测试没有 Sol 用量。

## 已完成的代码

`pilot/p4_responses_transport.py` 把原生系统提示显式传入 instructions，转换消息、工具schema、工具调用ID、工具结果和JSON格式，记录原始返回及真实token用量。没有附加 Codex/persona 提示，没有隐藏重试。温度、提示、模型或输出上限改变时停止；持续两次401停止。成本控制入口支持独立 P4_RUN_ROOT 与 Responses 提供商。

33项测试通过：原25项成本/认证回归，加8项Responses转换与参数核对测试。Ruff通过。正式实验配置的 capabilities_verified=False；protocol_stop.json 阻止搜索臂与判官验证发送新请求。历史OpenRouter运行与停止标记没有修改。

## 下一步

目前不能启动正式搜索比较：中转改写判官温度并忽略输出上限，后者会使发送前的费用预留失效；模型目录也不含价格。需要中转保留 temperature、max_output_tokens，并提供输入/输出/缓存单价及币种。满足这两项后复测接口，通过后再解除新运行的协议停止标记，沿用相同模型、原生温度与筛选/重测次数。

独立入口（当前会在任何模型调用前停止）：

```bash
P4_RUN_ROOT=pilot/runs/p4/v7_c4_relay_20261009 .venv/bin/python pilot/p4_cost_control_run.py --run --arm A0
```
