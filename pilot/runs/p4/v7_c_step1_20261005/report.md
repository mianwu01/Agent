# Tier C Step1：s010 异常核查

发现的是 VS 候选/忠实性过滤的原生协议漏检；严格重放没有发现 DB 或奖励记录错误。按用户要求，Step3 未启动。

|设置|成功/续写|终止类型|
|---|---|---|
|B1 persistent|24/24|{'transfer': 6, 'user_stop': 18}|
|v2 persistent|6/24|{'transfer': 20, 'user_stop': 4}|
|新 single-turn v2|5/12，Wilson95% CI [np.float64(0.19326031365875665), np.float64(0.6804886874504503)]|{'transfer': 7, 'user_stop': 5}|

新 single-turn 对照复用六个 v2 分支块，每块两次新续写，后续伙伴恢复 native；agent/partner temperature 保持1.0。按 draw 的原始结果见 [single_control.json](single_control.json)。该比较能检查分支块本身是否仍有影响，但历史批次并非配对随机版本实验，不能把差异全归因于 validator。

## 具体改变和 bug 证据

分支前客服的请求是：`Please disconnect the VPN next, then run a speed test to check your mobile data performance.` 原生规则明确规定，多动作请求必须要求客服一次指示一个动作。B1 的多个回复请求确认或一次一个动作，另一些执行了 VPN 工具；v2 的六个固定块都未执行工具，也都没有要求一次一个动作，四个直接要求客服断开 VPN。例：`Disconnect the VPN now. After that, I want a speed test...`。随后客服可能认为设备操作不在自己的工具集中并转人工。

全部六块均得到 Sol 忠实性模型的 `faithful=true`。这是保存下来的模型判断，不是合规真值。schema validator 检查 JSON 和工具参数，未覆盖多动作语义规则；过滤器因此接受了违反原生协议的分支回复。此证据支持协议过滤缺陷，不能证明18个失败全部由此导致。

[protocol_defect.json](protocol_defect.json) 保存原规则逐字引用及六个候选；[trajectory_diffs.json](trajectory_diffs.json) 保存24组首个伙伴差异、文本、工具、版本、忠实性 verdict、客服下一动作和终止类型。draw/rep 对齐只用于阅读，续写噪声并不配对。

## 重放和后续回合核查

6 个 v2 失败和6 个 B1 成功均严格机械重放，变更工具的返回值重放校验通过，最终断言向量与保存值相同，原生 evaluator 重算 reward 也相同。12 个重放未调用模型。B1/B2 未独立保存每条 suffix 的完整最终 DB，所以报告提供重新重放所得 DB 和断言对照，不声称对比不存在的 DB 快照。

|历史条件|伙伴回合|schema 错误回合|未映射保存 proposal|保存 DB 不一致|transfer 违规回合|解析到的错误事实/未观察事实|未解析设备句|
|---|---|---|---|---|---|---|---|
|B1|91|0|0|0|0|1/0|11|
|v2|77|0|0|0|0|0/0|21|

事实核查沿用冻结的 B2 机械解析器；未解析句子是未知，不能据此宣称不存在私有状态违背。后续每个映射回合的 verdict、执行字段及事实核查在 [trajectory_audit.json](trajectory_audit.json)。transfer 计数不等同于伙伴自行结束；保存的客服下一动作可检查实际来源。

冻结解析器把 B1 的一句过去时 `The VPN was connected ... but I’ve disconnected it` 标成当前 DB 不匹配：这是可由原文本和先前工具执行辨识的时态假阳性，不能当作实际错误报告。原始解析数保留，未重写解析器。协议漏检也不代表 v2 validator 代码新引入了问题；B1 与 v2 都沿用相同的语义过滤，旧批次亦有多动作工具执行。版本差异、候选抽样和独立续写均混杂。

Step2 的全部15个案例已按新规则重分类，见 [分类报告](../v7_c_step2_20261005/report.md)。规则在任何新续写前冻结；多类命中与聚合约定均公开。

## 成本和下一步

本轮仅新增12次 suffix，零新 proposal/judge，agent/partner 调用均保存在独立 redacted request ledger。{"request_records": 51, "returned_usage_requests": 51, "unknown_usage_requests": 0, "by_role": {"agent": {"requests": 24, "prompt_tokens": 193039, "completion_tokens": 2321, "total_tokens": 195360, "unknown_usage_requests": 0}, "user": {"requests": 27, "prompt_tokens": 95693, "completion_tokens": 623, "total_tokens": 96316, "unknown_usage_requests": 0}}}。历史输入 hash 检查通过。

Step3 尚未运行。应先明确修复上述原生协议漏检，再冻结搜索比较的定义和全部预算拆分。当前不能把 v2 persistent 当作已确认原生忠实的搜索生成器。
