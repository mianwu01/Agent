# P4 v7 C2 修订：persona、抽样重标与搜索比较

所有标签均为程序检查或模型判断；原生生成prompt、agent/partner温度1.0保持原设定。历史报告和数据保留。

## 规则清理

删除13条标题/角色/上下文行，15条角色特征单列persona；specific persona指导通用合作风格的解释，不覆盖机械与场景限制。只向标签器传ID、分类和逐字正文，审计位置保留在规则文件。

|ID|类别|原文|
|---|---|---|
|r_8b35de6a003c7475|mechanical|- Generate one message at a time, maintaining natural conversation flow.|
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
|r_c4ae37936687d0fd|scenario|You are unable to send MMS messages using your messaging app for the past few hours.|
|r_833b9ec270e28c77|scenario|You want to fix it and successfully send an MMS message.|
|r_389216a996a76dd5|scenario|You are John Smith with phone number 555-123-2002.|
|r_6542d4aea424512f|scenario|You are currently abroad in France.|
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
|r_5ff97bc20ffda1a0|persona|As a 41-year-old office administrator, you use your cellphone daily for both work and personal tasks.|
|r_6bd5b4908ad9ada1|persona|While you're familiar with common phone functions, you wouldn't call yourself a tech enthusiast.|
|r_839bcb7842d8e618|persona|Your technical skills are average - you handle standard smartphone features like calls, texts, email, and basic apps with ease.|
|r_73dca33eed480fd7|persona|You understand the fundamental settings, but prefer clear, step-by-step guidance when trying something new.|
|r_a3a56f78b2ac328e|persona|In interactions, you're naturally friendly and patient.|
|r_2e7baec1162f6e50|persona|When receiving help, you listen attentively and aren't afraid to ask questions.|
|r_a79415ee1cb52083|persona|You make sure to confirm your understanding and provide detailed feedback on each instruction you receive.|
|r_a3f61e7e371c229a|persona|At 64 years old, you're a retired librarian who keeps your phone use simple - mainly for calls, texts, and capturing photos of your grandchildren.|
|r_f9c69aab4c2e4ede|persona|Technology in general makes you feel uneasy and overwhelmed.|
|r_474d83d25477b5d6|persona|Your technical knowledge is quite limited.|
|r_c50f196a53b6f208|persona|Step-by-step instructions often confuse you, and technical terms like "VPN" or "APN" might as well be a foreign language.|
|r_a00db9d2bdb08b03|persona|You only share information when specifically asked.|
|r_1701b4383fe57e18|persona|When dealing with technology, you tend to get flustered quickly.|
|r_92a0f447b4390f1a|persona|You need constant reassurance and often interrupt with anxious questions.|
|r_cf5b8f8f2d52cce6|persona|Simple requests like "reboot the phone" can trigger worries about losing precious photos.|
|r_4df825aefa368fdb|scenario|You are currently at home in the United States.|
|native_user_schema|mechanical|Only native user tools; arguments validate against native JSON schemas.|
|native_tool_provenance|mechanical|Tool-result messages must be the actual native environment outputs with matching call ids.|
|native_format|mechanical|Native role/content/tool format uses inclusive OR: content, tools, or both are legal; inline tool-message text is hidden from the agent.|

## 15个确认案例

|案例|状态|类|有效|规则标签|偏离规则|
|---|---|---|---|---|---|
|c000|s005|unclear|True|in_rule|无|
|c003|s008|hard_for_both|True|in_rule|无|
|c007|s023|hard_for_both|True|in_rule|无|
|c009|s028|capability_dependent|True|in_rule|无|
|c010|s030|hard_for_both|True|in_rule|无|
|c011|s030|hard_for_both|True|in_rule|无|
|c012|s030|hard_for_both|True|in_rule|无|
|c015|s035|unclear|True|in_rule|无|
|c018|s016|beneficial_other|True|in_rule|无|
|c019|s016|beneficial_other|True|in_rule|无|
|c020|s023|unclear|True|in_rule|无|
|c023|s034|beneficial_disclosure|True|out_of_rule|r_e1f01f1a556442b4|
|c024|s034|beneficial_disclosure|True|out_of_rule|r_68cc06ad7063178d|
|c028|s038|beneficial_other|True|out_of_rule|r_68cc06ad7063178d|
|c030|s017|capability_dependent|True|out_of_rule|r_e1f01f1a556442b4|

完整case标签已完成15/15，轨迹联合标签完成300/300。未完成输入保留未知，不能作有效/无越界结论。

## 持续轨迹抽样

|cohort|分层|persistent成功/n|single成功/n|差|task-cluster95%CI|
|---|---|---|---|---|---|
|B1|all_raw|33/80|50/80|-0.21250000000000002|[np.float64(-0.3295454545454546), np.float64(-0.125)]|
|B1|all_valid|29/74|46/73|-0.23824509440947794|[np.float64(-0.35729748374703957), np.float64(-0.15440020790020784)]|
|B1|in_rule|19/48|22/37|-0.1987612612612613|[np.float64(-0.3889398326898327), np.float64(-0.014812091503267942)]|
|B1|out_of_rule|10/26|24/36|-0.282051282051282|[np.float64(-0.5607112794612795), np.float64(-0.061322230964245196)]|
|v2_Luna|all_raw|33/80|24/40|-0.1875|[np.float64(-0.3472222222222222), np.float64(0.013932291666666579)]|
|v2_Luna|all_valid|23/69|21/34|-0.2843137254901961|[np.float64(-0.48556944444444444), np.float64(-0.056779523725584057)]|
|v2_Luna|in_rule|15/48|12/19|-0.319078947368421|[np.float64(-0.5001482213438735), np.float64(-0.0572906993957501)]|
|v2_Luna|out_of_rule|8/21|9/15|-0.21904761904761905|[np.float64(-0.6113095238095239), np.float64(0.1005775072989821)]|

抽样预定配额：B1 native40、single80、persistent80；v2 Luna persistent80、Sol persistent20，共300条，未按结果筛选。每状态/条件/规则标签的原始成功数、分母和score区间在relabel_summary.json。

这是预先分层抽样后的历史描述，过滤有效性与style会改变样本组成，不作因果中介解释。每条轨迹的一次Sol调用联合判定所有适用规则和伙伴回合。

## 搜索比较

每臂预计102,752,639tokens（1000历史token suffix-equivalents），五臂预计513,763,193tokens，低于B1总用量三倍上限1,179,377,832。包含筛选、复测、Sol检查及场景judge成本。仅确认案例进行全style/persona标注；筛选回合只作必要有效性检查。

|Arm|完成|retest|verified|all valid distinct/1000|in_rule distinct/1000|returned tokens|
|---|---|---|---|---|---|---|
|A0|False|0|0|0.0|0.0|36449601.4|
|A1|False|0|0|0.0|0.0|24059289.4|
|A2|False|0|0|0.0|0.0|5355971.4|
|A3|False|0|0|0.0|0.0|22654712.4|
|A4|False|0|0|0.0|0.0|4068482.4|

各类别效率及95%任务簇区间（每1000 suffix-equivalents）：

|Arm|范围|类别|distinct|效率|95%CI|
|---|---|---|---|---|---|

配对任务簇效率差（探索性，未完成臂不支持排名）：

|比较|范围|差/1000|95%CI|双方完成|
|---|---|---|---|---|
|A3 - A2|all_valid|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A3 - A2|in_rule|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A2 - A0|all_valid|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A2 - A0|in_rule|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A3 - A0|all_valid|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A3 - A0|in_rule|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A2 - A1|all_valid|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A2 - A1|in_rule|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A3 - A1|all_valid|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A3 - A1|in_rule|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A2 - A4|all_valid|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A2 - A4|in_rule|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A3 - A4|all_valid|0.0|[np.float64(0.0), np.float64(0.0)]|False|
|A3 - A4|in_rule|0.0|[np.float64(0.0), np.float64(0.0)]|False|

A0：统计同方向存活0；完整规则有效0；Sol检查完成0。已知原生持续/原生参考同分布的阳性：[]，保留原始计数但不当作真实效应证据。

A1：统计同方向存活0；完整规则有效0；Sol检查完成0。已知原生持续/原生参考同分布的阳性：[]，保留原始计数但不当作真实效应证据。

A2：统计同方向存活0；完整规则有效0；Sol检查完成0。已知原生持续/原生参考同分布的阳性：[]，保留原始计数但不当作真实效应证据。

A3：统计同方向存活0；完整规则有效0；Sol检查完成0。已知原生持续/原生参考同分布的阳性：[]，保留原始计数但不当作真实效应证据。

A4：统计同方向存活0；完整规则有效0；Sol检查完成0。已知原生持续/原生参考同分布的阳性：[]，保留原始计数但不当作真实效应证据。

搜索全部完成前，不从不同完成进度推断效率优劣。两次连续401触发跨控制器停止文件；停止后不再发新请求，已在途请求保留账本。

## 当前两项回答

确认有害案例的规则内/规则外数量：{'in_rule': 9, 'out_of_rule': 1}（完整度15/15）。这表示规则兼容性，不代表实测原生q概率。

循环是否更高效：以完成的独立复测和相同完整预算为依据；未齐全时暂不下结论。

## 当前停止原因

五臂均未完成，没有已完成独立复测或verified案例，不能用0值比较算法效率。A0/A2曾收到空用户回复，A1/A4曾收到规则覆盖不完整的模型标签；已离线修补其拒绝/重试处理。A3账本确认Luna与Sol均返回Insufficient account balance，已停止所有新模型请求；余额恢复前不会自动重启。所有已完成轨迹、原始失败账本与调用成本保留，300条轨迹标签和15例离线比例表已完成。

## 实现问题与恢复

条件性‘我可以转人工’曾被宽泛regex误判成强制转接；审计392次A1错误拒绝，未发现受影响的已接受回复，A0审计无同类影响。修正为明确肯定的转接公告，排除条件、提议、否定；6项回归测试通过。窄口径错误循环成本：393次调用、返回1583504tokens、未知预留7550tokens。全部保留并计入同一臂预算；已完成结果复用，未完成续写的伙伴缓存归档后重跑。比较涉及实现修复开销，需结合该项成本解读，不把浪费隐藏为零。

## 确认案例的原生同类行为比例（离线）

复用冻结E1行为两轴标签，Sol主表、Luna对照；同状态6次原生回复，零新增模型调用。不是24次续写；独立16次原生参考另给机械工具序列比例，不冒充模型行为标签。

|案例|状态|Sol独立同类/n|95%CI|Luna独立同类/n|
|---|---|---|---|---|
|c000|s005|3/6|[0.1876163064826506, 0.8123836935173494]|3/6|
|c003|s008|0/6|[2.7755575615628914e-17, 0.3903342879021653]|2/6|
|c007|s023|3/6|[0.1876163064826506, 0.8123836935173494]|1/6|
|c009|s028|0/6|[2.7755575615628914e-17, 0.3903342879021653]|4/6|
|c010|s030|0/6|[2.7755575615628914e-17, 0.3903342879021653]|4/6|
|c011|s030|3/6|[0.1876163064826506, 0.8123836935173494]|4/6|
|c012|s030|3/6|[0.1876163064826506, 0.8123836935173494]|4/6|
|c015|s035|0/6|[2.7755575615628914e-17, 0.3903342879021653]|6/6|
|c018|s016|0/5|[0.0, 0.43448246478317476]|2/5|
|c019|s016|1/6|[0.030053369748306635, 0.5635028221864702]|1/6|
|c020|s023|0/5|[0.0, 0.43448246478317476]|0/5|
|c023|s034|1/6|[0.030053369748306635, 0.5635028221864702]|2/6|
|c024|s034|0/6|[2.7755575615628914e-17, 0.3903342879021653]|1/6|
|c028|s038|2/6|[0.09677141110578041, 0.700006684861608]|0/6|
|c030|s017|0/5|[0.0, 0.43448246478317476]|1/5|

[完整离线表、工具序列和s030文本特征](../v7_c2_step2_20261006_r2/native_behavior_prevalence_20261006/report.md)。0/6并不等于不可能；标签是粗粒度模型判断，共享标签不证明共享因果机制。候选来自原生q时，完整JSON另报去掉自身的比例。

## 模型调用与用量

|范围|角色|请求模型|返回模型|响应数|返回tokens|未知/在途|
|---|---|---|---|---|---|---|
|step1|connectivity_probe|gpt-5.6-luna|gpt-5.6-luna|1|22|0|
|step1|connectivity_probe|gpt-5.6-sol|gpt-5.6-sol|1|33|0|
|step2|rule_labeler_batch|openai/gpt-5.6-sol|gpt-5.6-sol-2026-07-09|105|1488685|0|
|step2|rule_labeler_batch|openai/gpt-5.6-sol|gpt-5.6-sol|214|3114012|0|
|step2|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol-2026-07-09|5|25869|0|
|step2|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol|18|112072|0|
|step2|rule_labeler_batch|openai/gpt-5.6-sol|None|0|0|24|
|step2|rule_labeler|openai/gpt-5.6-sol|None|0|0|19|
|step2|rule_labeler_transport_probe_no_effort|gpt-5.6-sol|None|0|0|1|
|step2|rule_labeler_transport_probe|gpt-5.6-sol|None|0|0|1|
|step2|rule_labeler_json_mode_probe|gpt-5.6-sol|None|0|0|1|
|step2|rule_labeler_stream_probe|gpt-5.6-sol|None|0|0|1|
|A0|agent|openai/gpt-5.6-luna|gpt-5.6-luna|2771|20809720|0|
|A0|user|openai/gpt-5.6-luna|gpt-5.6-luna|2617|8476082|0|
|A0|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol|1511|6931483|0|
|A0|vs_proposal|openai/gpt-5.6-luna|gpt-5.6-luna|25|76668|0|
|A0|user|openai/DeepSeek-V4.1-Flash|DeepSeek-Flash|31|126130|0|
|A0|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol-2026-07-09|7|27165|0|
|A0|rule_labeler|openai/gpt-5.6-sol|None|0|0|8|
|A0|agent|openai/gpt-5.6-luna|None|0|0|3|
|A0|user|openai/gpt-5.6-luna|None|0|0|5|
|A1|vs_proposal|openai/gpt-5.6-luna|gpt-5.6-luna|1760|6703332|0|
|A1|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol|968|4431276|0|
|A1|agent|openai/gpt-5.6-luna|gpt-5.6-luna|1572|11912121|0|
|A1|user|openai/gpt-5.6-luna|gpt-5.6-luna|310|968786|0|
|A1|user|openai/DeepSeek-V4.1-Flash|DeepSeek-Flash|6|22741|0|
|A1|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol-2026-07-09|5|18680|0|
|A1|vs_proposal|openai/gpt-5.6-luna|None|0|0|2|
|A1|rule_labeler|openai/gpt-5.6-sol|None|0|0|2|
|A2|user|openai/gpt-5.6-luna|gpt-5.6-luna|391|1226783|0|
|A2|agent|openai/gpt-5.6-luna|gpt-5.6-luna|424|3073173|0|
|A2|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol|242|1053662|0|
|A3|user|openai/DeepSeek-V4.1-Flash|DeepSeek-Flash|760|3533646|0|
|A3|vs_proposal|openai/gpt-5.6-luna|gpt-5.6-luna|157|616727|0|
|A3|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol|989|5452705|0|
|A3|user|openai/gpt-5.6-luna|gpt-5.6-luna|1217|4219835|0|
|A3|agent|openai/gpt-5.6-luna|gpt-5.6-luna|1121|8829446|0|
|A3|rule_labeler|openai/gpt-5.6-sol|None|0|0|2|
|A3|agent|openai/gpt-5.6-luna|None|0|0|2|
|A3|vs_proposal|openai/gpt-5.6-luna|None|0|0|2|
|A4|rule_labeler|openai/gpt-5.6-sol|gpt-5.6-sol|181|963877|0|
|A4|agent|openai/gpt-5.6-luna|gpt-5.6-luna|289|2120481|0|
|A4|user|openai/gpt-5.6-luna|gpt-5.6-luna|308|981771|0|

未知或已中断请求不按零成本处理；搜索预算另以输入加最大输出预留量计入，历史标注的未知量保留原始账本。

## 2026-10-07 程序化动作审计补充

[完整离线审计](../v7_c2_step2_action_20261007/report.md)覆盖全部15个确认案例，无新模型调用。此前粗粒度行为标签不能用来判断“原生几乎不演”。s030 原始 q 有4/6当轮未执行请求操作且提问；独立原生分别5/16、5/16、8/16，这些续写全部成功并在下一伙伴回合执行模式切换。候选块的已验证效果仍存在，但该特征单独不足以解释它。10个有害例子也并非同一类型：包括提问不执行、1GB授权、暂不给购买授权、开场信息以及执行操作后仍降低成功率的回复。1GB案例的部分失败仅涉及精确2GB断言，已单列。搜索比较尚无足够独立重测结果，不能报告方法效率优势。

## 2026-10-07 操作归属离线补充

[程序化委托审计](../v7_c2_step2_delegation_20261007/report.md)：c003/c010严格委托手机操作后候选成功3/16、4/16，后续转人工均13/16；对应原生均未检出严格委托。但s016/s034的36条独立原生委托测速回复全部立即转人工且失败。该交互弱点成立，原生总体不演的解释不成立。c000/c009一般诊断请求不强行归为用户工具委托。零新模型调用。

## 2026-10-07 全912条原生轨迹统计

[全量离线统计](../v7_c2_native912_20261007/report.md)：912条运行有678条失败；17条失败包含用户委托测速后立即转人工，占失败2.5%，任务聚类95% CI 0.9%–4.4%。移动数据任务为17/226（7.5%）。17次转人工理由均明确是没有测速工具。这个数字是失败中出现该路径的比例；修复可挽回比例待干预验证。零新模型调用。
