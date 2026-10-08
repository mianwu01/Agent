# P4 v7 Tier C：异常核查与案例重分类总报告

Step 1、2 已完成。s010 的严格重放没有发现 DB 或奖励记录错误，但 VS 候选和忠实性过滤漏掉了原生多动作协议要求。按本轮计划的 bug-stop 指令，Step 3 搜索循环比较未启动，尚无各搜索臂的效率结论。

本报告统一呈现两步结果；各步骤目录中的原报告、冻结计划、原始结果、模型 verdict、请求账本和审计文件保留。以下类别是机械操作性类别，忠实性 verdict 是模型判断，均不是人工标签。agent/partner 温度保持1.0。

## Step 1：s010 异常核查dou

发现的是 VS 候选/忠实性过滤的原生协议漏检；严格重放没有发现 DB 或奖励记录错误。按用户要求，Step3 未启动。

|设置|成功/续写|终止类型|
|---|---|---|
|B1 persistent|24/24|{'transfer': 6, 'user_stop': 18}|
|v2 persistent|6/24|{'transfer': 20, 'user_stop': 4}|
|新 single-turn v2|5/12，Wilson95% CI [0.19326031365875665, 0.6804886874504503]|{'transfer': 7, 'user_stop': 5}|

新 single-turn 对照复用六个 v2 分支块，每块两次新续写，后续伙伴恢复 native；agent/partner temperature 保持1.0。相对历史 v2 persistent 的成功率差为 +0.1667，Newcombe95% CI [-0.1325, 0.4608]；区间包含零，不能量化后续持续行为的额外影响。按 draw 的原始结果见 [single_control.json](../v7_c_step1_20261005/single_control.json)。该比较能检查分支块本身是否仍有影响，但历史批次并非配对随机版本实验，不能把差异全归因于 validator。

### 具体改变和 bug 证据

分支前客服的请求是：`Please disconnect the VPN next, then run a speed test to check your mobile data performance.` 原生规则明确规定，多动作请求必须要求客服一次指示一个动作。B1 的多个回复请求确认或一次一个动作，另一些执行了 VPN 工具；v2 的六个固定块都未执行工具，也都没有要求一次一个动作，四个直接要求客服断开 VPN。例：`Disconnect the VPN now. After that, I want a speed test...`。随后客服可能认为设备操作不在自己的工具集中并转人工。

全部六块均得到 Sol 忠实性模型的 `faithful=true`。这是保存下来的模型判断，不是合规真值。schema validator 检查 JSON 和工具参数，未覆盖多动作语义规则；过滤器因此接受了违反原生协议的分支回复。此证据支持协议过滤缺陷，不能证明18个失败全部由此导致。

[protocol_defect.json](../v7_c_step1_20261005/protocol_defect.json) 保存原规则逐字引用及六个候选；[trajectory_diffs.json](../v7_c_step1_20261005/trajectory_diffs.json) 保存24组首个伙伴差异、文本、工具、版本、忠实性 verdict、客服下一动作和终止类型。draw/rep 对齐只用于阅读，续写噪声并不配对。

### 重放和后续回合核查

6 个 v2 失败和6 个 B1 成功均严格机械重放，变更工具的返回值重放校验通过，最终断言向量与保存值相同，原生 evaluator 重算 reward 也相同。12 个重放未调用模型。B1/B2 未独立保存每条 suffix 的完整最终 DB，所以报告提供重新重放所得 DB 和断言对照，不声称对比不存在的 DB 快照。

|历史条件|伙伴回合|schema 错误回合|未映射保存 proposal|保存 DB 不一致|transfer 违规回合|解析到的错误事实/未观察事实|未解析设备句|
|---|---|---|---|---|---|---|---|
|B1|91|0|0|0|0|1/0|11|
|v2|77|0|0|0|0|0/0|21|

事实核查沿用冻结的 B2 机械解析器；未解析句子是未知，不能据此宣称不存在私有状态违背。后续每个映射回合的 verdict、执行字段及事实核查在 [trajectory_audit.json](../v7_c_step1_20261005/trajectory_audit.json)。transfer 计数不等同于伙伴自行结束；保存的客服下一动作可检查实际来源。

冻结解析器把 B1 的一句过去时 `The VPN was connected ... but I’ve disconnected it` 标成当前 DB 不匹配：这是可由原文本和先前工具执行辨识的时态假阳性，不能当作实际错误报告。原始解析数保留，未重写解析器。协议漏检也不代表 v2 validator 代码新引入了问题；B1 与 v2 都沿用相同的语义过滤，旧批次亦有多动作工具执行。版本差异、候选抽样和独立续写均混杂。

## Step 2：全部15个案例的重分类

按冻结优先级给出主类，同时保留所有命中规则。金额精确断言仅包含本批的 assert_data_refueling_amount；奖励规格判断按失败方向合并两种 agent 的失败：有害案例用固定块，有益案例用 native reference；逐 agent 原始数也保留。范围修正与原始版本均在下文公开，表格金额失败列仍列固定块的诊断。区间未校正多重比较。这些是操作性类别，不是人类标注或不可行性证明。

|Case|State|旧类|新类|仅金额失败/固定块失败（Luna；Sol）|
|---|---|---|---|---|
|c000|s005|unclear|unclear|0/13；0/8|
|c003|s008|unclear|hard_for_both|0/13；0/11|
|c007|s023|partner_sabotage_or_task_infeasible_probe|hard_for_both|5/15；4/15|
|c009|s028|interaction_failure|capability_dependent|0/15；1/7|
|c010|s030|partner_sabotage_or_task_infeasible_probe|hard_for_both|0/12；0/14|
|c011|s030|partner_sabotage_or_task_infeasible_probe|hard_for_both|0/7；0/12|
|c012|s030|partner_sabotage_or_task_infeasible_probe|hard_for_both|0/4；0/13|
|c015|s035|partner_sabotage_or_task_infeasible_probe|unclear|1/16；10/16|
|c018|s016|beneficial_directness_check|beneficial_other|0/5；0/1|
|c019|s016|beneficial_directness_check|beneficial_other|0/1；0/0|
|c020|s023|unclear|unclear|0/12；0/7|
|c023|s034|beneficial_directness_check|beneficial_disclosure|0/6；0/13|
|c024|s034|beneficial_directness_check|beneficial_disclosure|0/0；0/0|
|c028|s038|beneficial_directness_check|beneficial_other|0/1；0/1|
|c030|s017|interaction_failure|capability_dependent|0/14；0/0|

主类计数：`hard_for_both` 5、`capability_dependent` 2、`beneficial_disclosure` 2、`beneficial_other` 3、`unclear` 3；`reward_spec_mismatch` 和 `infeasible_after_block` 均为0。

所有原始成功数、分母、区间、并列命中规则及披露证据见 [reclassification.json](../v7_c_step2_20261005/reclassification.json)。披露类别依赖冻结的机械事实解析器；未匹配的句子不算已验证事实。

聚合敏感性：c015 在 Sol 固定块的16个失败中，有10个仅未满足精确补流量断言，符合逐 agent 的 ≥ 半数阅读；Luna 为1/16，合并为11/32，所以冻结的合并规则把它列为 unclear。这个类别不能掩盖已发现的奖励规格问题。两种阅读都在 [aggregation_sensitivity.json](../v7_c_step2_20261005/aggregation_sensitivity.json) 保留；本次不改冻结规则。

规则范围修正：初版把 reward_spec_mismatch 仅写成有害案例的 fixed 失败，未覆盖有益案例的 native 失败。已在 [plan_amendment_reward_spec_scope.json](../v7_c_step2_20261005/plan_amendment_reward_spec_scope.json) 公开修正，原 plan 不变。逐案例的失败方向诊断见 [failing_direction_diagnostic.json](../v7_c_step2_20261005/failing_direction_diagnostic.json)；5个有益案例的原生失败均没有仅金额失败，15个主类全部不变。修正是在查看结果后做的，不声称为原始预注册。未来案例使用修正后的范围。

## 成本、验证与后续状态

仅新增12次 single-turn suffix；Step 2 全部离线。没有新增 proposal 或 judge 调用。

|调用角色|请求数|输入 tokens|输出 tokens|总 tokens|
|---|---:|---:|---:|---:|
|agent|24|193039|2321|195360|
|user|27|95693|623|96316|

共51条请求记录，全部返回 usage；总计291676 tokens。账本和原始计数见 [token_accounting.json](../v7_c_step1_20261005/token_accounting.json)。输入/输出别名未重复相加。

289份历史 s010 输入的 hash 未变；6项验证通过，Ruff lint/format 通过。详细记录见 [Step 1 audit](../v7_c_step1_20261005/audit.json) 和 [Step 2 audit](../v7_c_step2_20261005/audit.json)。

Step 3 尚未运行。应先修复并验证原生协议漏检，再冻结搜索比较的定义和全部预算拆分。现有结果不能证明全部成功率下降都由协议缺陷导致，也不能把 v2 persistent 视为已确认原生忠实的搜索生成器。
