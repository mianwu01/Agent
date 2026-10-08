# P4 v7 Tier C continued：规则、重标与搜索准备

**当前状态：15个固定案例重标完成；sanity和历史逐回合重标尚未完成；Step3未启动。四条既有凭据均返回HTTP401，已保存认证诊断。** 本报告不把缺失标签视为有效、不制造后过滤的成功率，也不把未运行的搜索臂记成零发现。

固定项目标准：mechanical与scenario违背使回合无效，style偏离保留并逐条标注。原C1把多动作澄清当作协议bug的解释，在本项目标准下撤回；历史报告保留。所有Sol标签都是模型判断，新增格式标签来自程序字段检查，没有人工标签。

## Step1：逐字规则与生成器

完整20个原生system prompts、逐字quote的位置及所属任务见 [rules_v2.json](../v7_c2_step1_20261006/rules_v2.json)。原抽取版本 [rules.json](../v7_c2_step1_20261006/rules.json) 保留，格式边界修订见 [amendment](../v7_c2_step1_20261006/plan_amendment_native_format.json)。表中正文上下文也保留用于覆盖，不适用的上下文不算风格违背；runtime-derived行明确区分于逐字原生规则。

|Rule ID|分类|逐字原文或明确标识的runtime要求|
|---|---|---|
|r_1e737ea758eb1c8e|style|You are playing the role of a customer contacting a customer service representative agent.|
|r_dcfc715fec3dacfd|style|Your goal is to simulate realistic customer interactions while following specific scenario instructions.|
|r_88a429093deb7bfc|style|You have some tools to perform the actions on your end that might be requested by the agent to diagnose and resolve your issue.|
|r_8b35de6a003c7475|mechanical|- Generate one message at a time, maintaining natural conversation flow.|
|r_5f8b06221f3269f7|mechanical|- At each turn you can either:|
|r_fcbdfae4ccb65ed9|mechanical|- Send a message to the agent.|
|r_de7df1a625f0ad90|mechanical|- Make a tool call to perform an action requested by the agent.|
|r_5112db5336c2d337|style|- You cannot do both at the same time.|
|r_1eae9c2edc5d171e|scenario|- Strictly follow the scenario instructions you have received.|
|r_2e35bfc1887f4509|scenario|- Never make up or hallucinate information not provided in the scenario instructions.|
|r_cfd9987f14a505c6|scenario|Information that is not provided in the scenario instructions should be considered unknown or unavailable.|
|r_4ab8da09699d58e6|mechanical|- Never make up the results of tool calls that the agent has requested, you must ground your responses based on the results of tool calls if the agent has requested.|
|r_426e5da492dd58db|style|- If you made an error in a tool call and get an error message, fix the error and try again.|
|r_83868b95ba8ac68b|scenario|- All the information you provide to the agent must be grounded in the information provided in the scenario instructions or the results of tool calls.|
|r_65cac7d72310e405|style|- Avoid repeating the exact instructions verbatim.|
|r_40362225f2f88dfe|style|Use paraphrasing and natural language to convey the same information|
|r_5b21336836eb711e|style|- Disclose information progressively.|
|r_68cc06ad7063178d|style|Wait for the agent to ask for specific information before providing it.|
|r_d69a30a8ddd03b78|style|- Only call a tool if the agent has requested it or if it is necessary to answer a question the agent has asked.|
|r_f5ef4953402ec3e8|style|Ask clarifying questions if you do not know what action to take.|
|r_0713017396e2ad22|style|- If the agent asks multiple actions to perform, state that you cannot perform multiple actions at once, and ask the agent to instruct you one action at a time.|
|r_008e12545ebd063c|mechanical|- Your messages when performing tool calls will not be displayed to the agent, only the messages without tool calls will be displayed to the agent.|
|r_a8cf8169d2749c66|style|- The goal is to continue the conversation until the task is complete.|
|r_d412baeb552eaeab|mechanical|- If the instruction goal is satisified, generate the '###STOP###' token to end the conversation.|
|r_35f62ccb0226724f|mechanical|- If you have been transferred to another agent, generate the '###TRANSFER###' token to indicate the transfer.|
|r_2213167e7b4cb0b2|mechanical|Only do this after the agent has clearly indicated that you are being transferred.|
|r_6c4d26b8fc1206e3|mechanical|- If you find yourself in a situation in which the scenario does not provide enough information for you to continue the conversation, generate the '###OUT-OF-SCOPE###' token to end the conversation.|
|r_a029d85162895cfd|style|Remember: The goal is to create realistic, natural conversations while strictly adhering to the provided instructions and maintaining character consistency.|
|r_c72eb7bd54873777|style|Instructions:|
|r_5fec7d44d60cec37|scenario|Domain: telecom|
|r_5c3a7fdffa7486e4|style|Reason for call:|
|r_c4ae37936687d0fd|scenario|You are unable to send MMS messages using your messaging app for the past few hours.|
|r_833b9ec270e28c77|scenario|You want to fix it and successfully send an MMS message.|
|r_d9743e4e531c9eed|scenario|Known info:|
|r_389216a996a76dd5|scenario|You are John Smith with phone number 555-123-2002.|
|r_6542d4aea424512f|scenario|You are currently abroad in France.|
|r_c122cde65d17ce5c|style|Task instructions:|
|r_e1f01f1a556442b4|style|If the agent suggests actions that don't immediately fix the issue, follow their guidance but express mild frustration after the first unsuccessful attempt.|
|r_7946e6e940597cc3|scenario|You are willing to refuel 2.0 GB of data if necessary, but you do not want to change your mobile data plan.|
|r_bd4131766e94ea95|style|If the tool call does not return updated status information, you might need to perform another tool call to get the updated status.|
|r_5145d3412a54869b|style|Whenever the agent asks you about your device, always ground your responses on the results of tool calls.|
|r_04c8d0b7a12fe3ae|style|For example: If the agent asks what the status bar shows, always ground your response on the results of the `get_status_bar` tool call.|
|r_d8739960cdcaaee3|style|If the agent asks if you are able to send an MMS message, always ground your response on the results of the `can_send_mms` tool call.|
|r_a4a1dde82cf92506|mechanical|Never make up the results of tool calls, always ground your responses on the results of tool calls.|
|r_800f06d0ccfd11e0|style|If you are unsure about whether an action is necessary, always ask the agent for clarification.|
|r_4a11a3c49eb7573e|scenario|You mobile data is not working properly.|
|r_18dc24f883426020|scenario|It either stops working or is very slow.|
|r_ed638c57407243a6|scenario|You want to fix it and absolutely want to get excellent internet speed on your phone.|
|r_f2611470af0d3f7f|scenario|You are not willing to accept any other internet speed (poor, fair or good).|
|r_9850fe284bfbf54b|scenario|You do not have access to wifi.|
|r_77d177d8c0106163|scenario|You will consider the issue resolved only when speed test returns excellent internet speed and nothing else.|
|r_7cd5e767ae56a58f|scenario|If it returns poor, fair or good, you will not consider the issue resolved.|
|r_c364eb29dc92b0e0|style|Persona:|
|r_5ff97bc20ffda1a0|scenario|As a 41-year-old office administrator, you use your cellphone daily for both work and personal tasks.|
|r_6bd5b4908ad9ada1|style|While you're familiar with common phone functions, you wouldn't call yourself a tech enthusiast.|
|r_839bcb7842d8e618|style|Your technical skills are average - you handle standard smartphone features like calls, texts, email, and basic apps with ease.|
|r_73dca33eed480fd7|style|You understand the fundamental settings, but prefer clear, step-by-step guidance when trying something new.|
|r_a3a56f78b2ac328e|style|In interactions, you're naturally friendly and patient.|
|r_2e7baec1162f6e50|style|When receiving help, you listen attentively and aren't afraid to ask questions.|
|r_a79415ee1cb52083|style|You make sure to confirm your understanding and provide detailed feedback on each instruction you receive.|
|r_a3f61e7e371c229a|scenario|At 64 years old, you're a retired librarian who keeps your phone use simple - mainly for calls, texts, and capturing photos of your grandchildren.|
|r_f9c69aab4c2e4ede|style|Technology in general makes you feel uneasy and overwhelmed.|
|r_474d83d25477b5d6|style|Your technical knowledge is quite limited.|
|r_c50f196a53b6f208|style|Step-by-step instructions often confuse you, and technical terms like "VPN" or "APN" might as well be a foreign language.|
|r_a00db9d2bdb08b03|style|You only share information when specifically asked.|
|r_1701b4383fe57e18|style|When dealing with technology, you tend to get flustered quickly.|
|r_92a0f447b4390f1a|style|You need constant reassurance and often interrupt with anxious questions.|
|r_cf5b8f8f2d52cce6|style|Simple requests like "reboot the phone" can trigger worries about losing precious photos.|
|r_4df825aefa368fdb|scenario|You are currently at home in the United States.|
|native_user_schema|mechanical|【runtime-derived，非原prompt原文】Only native user tools; arguments validate against native JSON schemas.|
|native_tool_provenance|mechanical|【runtime-derived，非原prompt原文】Tool-result messages must be the actual native environment outputs with matching call ids.|
|native_format|mechanical|【runtime-derived，非原prompt原文】Native role/content/tool format uses inclusive OR: content, tools, or both are legal; inline tool-message text is hidden from the agent.|

VS生成调用保留第一条native system prompt逐字不变，保留原生user-visible history，工具通过原生API schemas提供；唯一添加内容是k=5候选及概率的采样/JSON输出指令。按预先固定种子从5个候选均匀抽1个，概率记录但不作为权重；没有行为强化指令或研究者persona。原始请求账本可核对prompt。

机械检查覆盖原生工具与参数、实际native工具结果来源和终止tokens；场景事实与真实DB比较，过去时及不确定表达不自动按当前DB定罪（[解析范围修订](../v7_c2_step2_20261006/plan_amendment_scenario_claim_scope.json)），未能解析的内容由冻结Sol t=0按逐字规则判定。每个适用style规则单列状态，style不会进入拒绝条件。原生runtime允许content+tools并隐藏行内文本，因此提示中的“不能同时做两者”是style，而不是机械XOR门。

### Sanity：未完成，保留原始分母

|项目|当前数量|计划数量|
|---|---:|---:|
|已保存有效VS回合|55|60|
|符合最终采样过滤版本的已完成draw|55|60|
|native q逐规则标签|0|60|
|全部已保存VS回合的in_rule|15|分母55|
|全部已保存VS回合的out_of_rule|40|分母55|

旧过滤器曾因现在归为style的content+tools而拒绝s027:vs:d4；该单元列入重做清单，当前55个保存文件不包含它。恢复后需补齐该单元及其余缺失draw。原始记录保留，不抹掉这次错误过滤。style标签和规则分母见 [status.json](status.json)，native q比较与最终out_of_rule区间待完成60+60后报告。

拒绝原因原始计数（含已纠正的旧格式拒绝，不将它重新解释为最终标准的违规）：`{"VS_JSON_schema:'candidates'": 2, "VS_JSON_schema:message_has_both_text_and_tools": 1, "mechanical:required_transfer_token_missing_or_tools": 7, "DB_scenario:device.roaming_enabled": 5, "model_scenario:r_1eae9c2edc5d171e": 1, "model_scenario:r_2e35bfc1887f4509": 1, "model_scenario:r_cfd9987f14a505c6": 1, "model_scenario:r_83868b95ba8ac68b": 1}`。认证/JSON路由错误是执行失败，单列于ledger，不当作伙伴违规。

## Step2：15个固定案例

|Case|State|方向|既有案例类|机械违规|场景违规|style|偏离style规则ID|
|---|---|---|---|---|---|---|---|
|c000|s005|harmful|unclear|无|无|out_of_rule|r_5b21336836eb711e, r_68cc06ad7063178d|
|c003|s008|harmful|hard_for_both|无|无|in_rule|—|
|c007|s023|harmful|hard_for_both|无|无|in_rule|—|
|c009|s028|harmful|capability_dependent|无|无|in_rule|—|
|c010|s030|harmful|hard_for_both|无|无|out_of_rule|r_1e737ea758eb1c8e, r_dcfc715fec3dacfd, r_88a429093deb7bfc, r_a029d85162895cfd, r_5145d3412a54869b|
|c011|s030|harmful|hard_for_both|无|无|out_of_rule|r_0713017396e2ad22|
|c012|s030|harmful|hard_for_both|无|无|in_rule|—|
|c015|s035|harmful|unclear|无|无|in_rule|—|
|c018|s016|beneficial|beneficial_other|无|无|in_rule|—|
|c019|s016|beneficial|beneficial_other|无|无|out_of_rule|r_5b21336836eb711e, r_68cc06ad7063178d|
|c020|s023|harmful|unclear|无|无|out_of_rule|r_0713017396e2ad22|
|c023|s034|beneficial|beneficial_disclosure|无|无|out_of_rule|r_68cc06ad7063178d, r_d69a30a8ddd03b78, r_800f06d0ccfd11e0|
|c024|s034|beneficial|beneficial_disclosure|无|无|out_of_rule|r_68cc06ad7063178d, r_d69a30a8ddd03b78, r_e1f01f1a556442b4|
|c028|s038|beneficial|beneficial_other|无|无|out_of_rule|r_5b21336836eb711e, r_68cc06ad7063178d|
|c030|s017|harmful|capability_dependent|无|无|out_of_rule|r_e1f01f1a556442b4|

各rule的完整证据quote、programmatic DB检查及Sol场景判断保留在 [case_labels.json](../v7_c2_step2_20261006/case_labels.json) 和 mapped_labels/。原有类依据真实Luna/Sol retest、scope修正和原始区间沿用，没有新续写或新分类阈值。

|类|in_rule有效案例|out_of_rule有效案例|
|---|---:|---:|
|reward_spec_mismatch|0|0|
|hard_for_both|3|2|
|capability_dependent|1|1|
|infeasible_after_block|0|0|
|beneficial_disclosure|0|2|
|beneficial_other|1|2|
|unclear|1|2|

无效案例：无（15个均有效）。c015的Sol失败中10/16仅未满足精确补流量断言，但合并Luna后11/32，冻结合并规则仍为unclear；style/validity标签没有掩盖这项奖励规格问题。

### 持续伙伴的成功率分解：标签尚未齐全

已建立1752条历史轨迹、12028个伙伴回合实例的映射，共10590个唯一标签输入；其中288个已完成完整模型/程序标签。B1覆盖native/single/persistent及初始回合，v2覆盖全部240条Luna和72条Sol持续续写。机械与DB可独立继续离线检查，但缺失的场景判断与style标签保持未知。因此当前不能报告排除违规后的persistent−single差值或完整in_rule/out_of_rule分层区间。不是把未经检查的轨迹默认当作有效。

离线程序检查结果：`{"unique_inputs": 10590, "completed_checks": 10590, "mechanical_invalid_inputs": 420, "programmatic_DB_mismatch_inputs": 94, "format_style_out_of_rule_inputs": 31, "original_programmatic_summary_retained": true, "new_model_calls": 0}`。这些不是完整场景有效性判定，未解析规则仍需Sol判断。

## Step3：预计成本与执行状态

|Arm|预计tokens|目标suffix-equivalents|当前执行|
|---|---:|---:|---|
|A0|102,752,639|1000|未启动|
|A1|102,752,639|1000|未启动|
|A2|102,752,639|1000|未启动|
|A3|102,752,639|1000|未启动|
|A4|102,752,639|1000|未启动|

成本基准是B1 step2全部返回tokens/1024条saved suffix，得到每个suffix-equivalent 102752.638672 tokens；不同模型的token统一计量，不声称同价。B1总返回tokens 393,125,944，三倍上限1,179,377,832，五臂预计合计513,763,193，未超过上限。Step1/2和失败调用单独列账，不隐藏在搜索效率分母里。

预算拆分、buffer来源、selection公式、GT只记录的约束、独立16vs16 retest、Sol检查、case去重以及未知usage处理见 [plan.json](../v7_c2_step3_20261006/plan.json)；最终规则关联修订在其amendment中。模型目录列出了DeepSeek/Claude/Qwen，但尚未做可调用性probe，不能把目录存在当作实际运行。

因凭据失效，A0–A4没有fresh seed episode、screen、retest或Sol-check结果；目前不回答效率优劣，不生成虚假的曲线或三张案例卡。认证诊断见 [authentication_diagnostic.json](authentication_diagnostic.json)。

## 两个问题的当前答案

1. 10个已确认有害固定案例（含1个随机对照）中，当前逐条规则标签为 **in_rule 5个，out_of_rule 5个**。只看9个主要有害案例，in_rule5、out_of_rule4。这里in_rule是符合native风格规则的模型判定，不是实测该块在q下出现概率；out_of_rule也不意味着随机simulator绝对不可能生成。
2. 搜索循环是否更省预算：**尚不能判断**。搜索尚未启动，不能以准备好的代码或成本预测代替实验。

## 已发生的调用与恢复位置

|步骤/角色|请求记录|返回usage|未知usage|返回tokens|
|---|---:|---:|---:|---:|
|step1/rule_labeler|137|64|73|2796951|
|step1/user|1|1|0|2821|
|step1/vs_proposal|310|127|183|385735|
|step2/rule_labeler|3323|289|3034|13886441|

失败/中断请求usage未知，不按零计，也不把input/output aliases重复相加。JSON模式的两项传输格式修订、原始失败尝试、库存修订、格式边界修订均保留；没有重新训练或按效果调标签器。

恢复位置：先补齐最终生成器sanity draws及native基线标签；完成10,590个唯一历史标签；报告完整persistent split；再执行已冻结的搜索预算与family接口probe。此次暂停原因是四条凭据均HTTP401，不是预算阈值。
