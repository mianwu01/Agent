# 确认案例：程序化动作与购买量审计

零模型调用。原生同类行为主定义为：agent明确请求了用户工具操作，用户当轮没有执行任何被请求操作，而回复含问题或澄清标记。另报第一步未执行、完全无用户工具、完整执行所有步骤。缺乏用户操作请求的回合记N/A。购买量是用户授权给agent的数量，不等于用户执行设备操作。

|案例|状态|方向|候选程序特征|原始q未执行且提问|独立原生未执行且提问|独立原生仅第一步缺失且提问|
|---|---|---|---|---|---|---|
|c000|s005|harmful|no_action_or_purchase_request_at_branch|N/A|N/A|N/A|
|c003|s008|harmful|requested_device_action_omitted_with_question|0/6 (0.0%)|0/16 (0.0%)|0/16 (0.0%)|
|c007|s023|harmful|1GB_consent_choice, requested_device_action_omitted_without_question|0/6 (0.0%)|1/16 (6.2%)|1/16 (6.2%)|
|c009|s028|harmful|purchase_amount_not_given|N/A|N/A|N/A|
|c010|s030|harmful|requested_device_action_omitted_with_question|4/6 (66.7%)|5/16 (31.2%)|5/16 (31.2%)|
|c011|s030|harmful|requested_device_action_omitted_with_question|4/6 (66.7%)|5/16 (31.2%)|5/16 (31.2%)|
|c012|s030|harmful|requested_device_action_omitted_with_question|4/6 (66.7%)|8/16 (50.0%)|8/16 (50.0%)|
|c015|s035|harmful|1GB_consent_choice|N/A|N/A|N/A|
|c018|s016|beneficial|no_action_or_purchase_request_at_branch|N/A|N/A|N/A|
|c019|s016|beneficial|no_action_or_purchase_request_at_branch|N/A|N/A|N/A|
|c020|s023|harmful|requested_device_action_executed|0/5 (0.0%)|1/16 (6.2%)|1/16 (6.2%)|
|c023|s034|beneficial|no_action_or_purchase_request_at_branch|N/A|N/A|N/A|
|c024|s034|beneficial|no_action_or_purchase_request_at_branch|N/A|N/A|N/A|
|c028|s038|beneficial|no_action_or_purchase_request_at_branch|N/A|N/A|N/A|
|c030|s017|harmful|requested_device_action_executed, executed_test_reports_no_connection|0/5 (0.0%)|0/16 (0.0%)|0/16 (0.0%)|

上述频率的原始分子/分母、Wilson95%区间、匹配的请求原文、实际工具及参数均在per_case.json。原始q与独立参考分开；原生来源候选去掉自己。没有采用Sol/Luna行为类别。

## s030：同类动作特征是否也在原生成功中出现

|案例|原生未执行且提问的成功数|其余原生成功数|候选成功数|候选第一agent动作|
|---|---|---|---|---|
|c010|5/5|11/11|4/16|{'transfer_to_human_agents': 9, 'communication': 7}|
|c011|5/5|11/11|9/16|{'communication': 13, 'get_details_by_id': 1, 'transfer_to_human_agents': 2}|
|c012|8/8|8/8|12/16|{'communication': 13, 'transfer_to_human_agents': 3}|

## 购买量

|案例|候选当前授权GB|原始q授权1GB|独立原生授权1GB|候选成功|原生成功|候选仅精确容量断言未满足|
|---|---|---|---|---|---|---|
|c007|1.0|0/6 (0.0%)|0/16 (0.0%)|1/16|13/16|5|
|c009|None|0/6 (0.0%)|0/16 (0.0%)|1/16|8/16|0|
|c015|1.0|0/6 (0.0%)|0/16 (0.0%)|0/16|5/16|1|
|c020|2.0|0/5 (0.0%)|0/16 (0.0%)|4/16|14/16|0|

## 10个有害例子的执行路径

|案例|候选机械特征|候选/原生成功|候选/原生转人工数|候选/原生agent后续加购总量分布|
|---|---|---|---|---|
|c000|no_action_or_purchase_request_at_branch|3/16 vs 9/16|13 vs 8|{'2.0': 6, '0': 10} vs {'2.0': 16}|
|c003|requested_device_action_omitted_with_question|3/16 vs 15/16|13 vs 1|{'0': 16} vs {'0': 16}|
|c007|1GB_consent_choice, requested_device_action_omitted_without_question|1/16 vs 13/16|10 vs 4|{'1.0': 14, '2.0': 2} vs {'2.0': 16}|
|c009|purchase_amount_not_given|1/16 vs 8/16|14 vs 9|{'2.0': 2, '0': 14} vs {'2.0': 16}|
|c010|requested_device_action_omitted_with_question|4/16 vs 16/16|13 vs 1|{'0': 16} vs {'0': 16}|
|c011|requested_device_action_omitted_with_question|9/16 vs 16/16|8 vs 1|{'0': 16} vs {'0': 16}|
|c012|requested_device_action_omitted_with_question|12/16 vs 16/16|4 vs 2|{'0': 16} vs {'0': 16}|
|c015|1GB_consent_choice|0/16 vs 5/16|15 vs 11|{'1.0': 16} vs {'2.0': 16}|
|c020|requested_device_action_executed|4/16 vs 14/16|12 vs 3|{'2.0': 16} vs {'2.0': 16}|
|c030|requested_device_action_executed, executed_test_reports_no_connection|2/16 vs 9/16|14 vs 7|{'0': 16} vs {'0': 16}|

## 限制

这些是机械特征和保存路径的关联，不能证明某一个特征单独决定了结果。程序定义的动作类别仍可能把不同具体提问归为同类。一般“试试网络”映射为native run_speed_test，不把纯自然语言“试过了”当作已执行；测速返回No Connection仍算执行了测速。完成网络模式切换但没重启/测速与完全未执行分开。1GB用户授权未违反agent给出的up-to2GB选项；是否仅因reward精确容量要求失败单独计数。字段未读、因果意图、自然语言未被模式解析部分均不补造。

## 结论与补充核对

s030 的“原生几乎从不当轮不执行、先提问”解释不成立。原始 q 是 4/6；独立参考是 5/16、5/16、8/16。这些参考续写全部成功，而且全部在下一伙伴回合执行了要求的网络模式切换。候选固定块依然降低成功率，但这个动作特征不足以单独解释效果。c010 的下一 agent 动作有 9/16 直接转人工，而原生上述提问子集全部继续自然语言沟通。转人工也可能发生在任务已成功之后，不能直接当作失败。

s008 的对应原生频率是 0/6、0/16；这支持该特征在这批样本中少见，但 0/16 的 Wilson 95% 上限是 19.4%，并不证明原生不会产生。

10 个有害例子的特征构成：4 个未执行且提问（c003、c010–c012）；2 个授权 1GB（c007、c015，其中 c007 也未执行漫游但没提问）；1 个暂不给购买量授权（c009）；1 个开场信息差异（c000）；2 个已经执行请求却仍有害（c020、c030）。这是程序化描述，不是新的人工作因果分类。c000 的具体致因尚未确定。

|案例|候选已经出现的程序特征|原始 q 同特征|独立原生同特征|
|---|---|---|---|
|c007|none_requested_without_question|4/6 (66.7%)|14/16 (87.5%)|
|c009|amount_requested_but_no_numeric_consent|6/6 (100.0%)|15/16 (93.8%)|
|c020|any_requested_operation_executed|1/5 (20.0%)|2/16 (12.5%)|
|c030|any_requested_operation_executed|5/5 (100.0%)|16/16 (100.0%)|
|c030|negative_speed_test_observed|5/5 (100.0%)|16/16 (100.0%)|

这里只比较各个已定义特征，不把特征边际频率当成整段回复的等价频率。c020 的候选执行漫游并授权 2GB；c030 的候选执行测速并报告 No Connection，因此都不是“当轮没有执行”例子。

### 1GB 与精确评分断言

c007/s023 与 c015/s035 的原生授权 1GB 均为 0/6、0/16。候选后续 agent 实际购买量主要/全部为 1GB，而原生均为 2GB。区别首先是购买授权量，不是单纯有无执行。

|案例|Luna 候选失败数|其中仅精确容量断言失败|Sol 候选失败数|其中仅精确容量断言失败|
|---|---|---|---|---|
|c007|15/16|5/15|15/16|4/15|
|c015|16/16|1/16|16/16|10/16|

仅精确容量失败表示其他保存的任务断言都满足；不将其当作排障失败。其余失败还存在其他未满足断言。选择 1GB 符合该回合 up-to-2GB 的授权选项，不能据此断言用户破坏任务。保持原有类别定义，不因这份补充审计修改历史类别。

本轮使用 15 份个案卡、每案 16 条独立原生参考和 16 条候选续写（共 480 条 Luna 续写）及原始 q 回复；共享状态的原始 q 不作为多组独立观测合并。所有频率、Wilson 区间和逐条路径已保存。程序边界核对及数量/后续路径核对共 12 项通过，见 verification.json。没有任何新模型调用。搜索比较仍待余额恢复，已有未完成筛选不能支持效率结论。
