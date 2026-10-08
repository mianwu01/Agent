"""Create a local, outcome-blinded annotation packet without model calls."""

import json
import random

import p4_calibration as c

from tau2.data_model.tasks import Task


def main():
    """Hide labels, outcomes and strata, preserving the agent-visible projection."""
    c.activate()
    panel = c.p4.read(c.OUT / "review_panel.json")["items"]
    random.Random(2026100303).shuffle(panel)
    tasks = c.p4.read(c.OUT / "tasks.json")
    entries, mapping = [], []
    for number, item in enumerate(panel):
        identifier = f"episode_{number + 1:02d}"
        task = Task.model_validate(tasks[item["task_id"]])
        orch = c.NATIVE_BUILDER(c.p4.config(), task)
        sim = c.p4.read(c.OUT / "sources" / (item["sample_id"] + ".json"))
        visible = c.p4.agent_view(sim["messages"])
        entry = {
            "episode_id": identifier,
            "policy": orch.agent.domain_policy,
            "agent_tools": [t.openai_schema for t in orch.agent.tools],
            "transcript": visible,
        }
        entries.append(entry)
        mapping.append(
            {
                "episode_id": identifier,
                "sample_id": item["sample_id"],
                "input_sha256": c.p4.digest(entry),
                "source_sha256": c.p4.digest(sim),
            }
        )
    c.p4.save(c.OUT / "annotation_packet.json", entries)
    c.p4.save(
        c.OUT / "annotation_packet_manifest.json",
        {
            "mapping": mapping,
            "purpose": "Human independent candidate-process review before reading analysis. No reward, task ID, stratum, gold actions, hidden initialization or user-tool results in participant input.",
            "limits": "Knowledge of this conversation or prior analysis may compromise blinding; report participant exposure honestly. Wall-clock viewing time is approximate, not verified active review time.",
        },
    )
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    template = r"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>P4 独立候选标注</title>
<style>body{font:16px/1.6 system-ui;max-width:1150px;margin:30px auto;padding:0 20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:14px;font-size:13px}.message{border:1px solid #ccd6e4;padding:12px;margin:8px 0}.controls{position:sticky;top:0;background:white;border-bottom:1px solid #aaa;padding:12px;z-index:1}textarea{width:95%;min-height:65px}input,select,button{padding:7px;margin:5px}button{cursor:pointer}.note{background:#fff3d7;padding:14px}</style>
<h1>P4 独立候选过程标注</h1>
<p>请根据已有 policy、agent 工具和可见对话判断候选过程；先独立完成，再查看实验分析。每条选一个最早有证据的决策。这里不判断最终任务成败，也不将候选直接判为已确认机制。</p>
<p>A：指令与仍有效的可见状态证据矛盾。B：未知状态下发出无条件、依赖当前状态的写指令，且两种兼容状态下效果不同。C：明确以自己没有设备工具为由拒绝、停止或转人工，而 policy 中仍有适用的用户侧操作。other：其他有证据的候选过程。none：没有支持的候选。uncertain：证据不足。</p>
<p class="note">多步骤回复本身不构成 B；“进一步诊断仍有必要”本身不构成 C。检查合法转人工条件、用户拒绝、已有操作和证据是否过时。网页无需联网，标注保存在本浏览器，可导出 JSON。记录的是浏览停留时间，含空闲时间。</p>
<div class="controls"><button id="previous">上一条</button><span id="position"></span><button id="next">下一条</button><button id="export">导出标注 JSON</button><span id="progress"></span></div>
<h2 id="episode"></h2><details><summary>完整 policy</summary><pre id="policy"></pre></details><details><summary>agent 可直接调用的工具</summary><pre id="tools"></pre></details><div id="transcript"></div>
<h2>独立判断</h2><label>类别<select id="category"><option value="">请选择</option><option>A</option><option>B</option><option>C</option><option>other</option><option>none</option><option>uncertain</option></select></label>
<label>最早决策的 assistant 原始 index<input id="decision" type="number" min="0"></label>
<p>引用证据 index 与原文</p><textarea id="evidence"></textarea><p>判断理由与尚未排除的竞争解释</p><textarea id="rationale"></textarea>
<label>是否提前接触过本批分析或标签<select id="exposure"><option value="">请选择</option><option value="no">没有</option><option value="yes">有</option><option value="unsure">不确定</option></select></label><p id="validation"></p>
<script>
const entries=__DATA__;
const packetKey='p4_annotation_'+entries.map(e=>e.episode_id).join('_')+'_2026100303';
let answers=JSON.parse(localStorage.getItem(packetKey)||'{}'), position=0, opened=Date.now();
const ids=['category','decision','evidence','rationale','exposure'];
const get=id=>document.getElementById(id);
function persist(){const row=answers[entries[position].episode_id]||{};for(const id of ids)row[id]=get(id).value;row.wall_seconds=(row.wall_seconds||0)+(Date.now()-opened)/1000;opened=Date.now();answers[entries[position].episode_id]=row;localStorage.setItem(packetKey,JSON.stringify(answers));get('progress').textContent=Object.values(answers).filter(a=>a.category).length+'/'+entries.length+' 条已选类别';}
function render(){opened=Date.now();const e=entries[position];get('episode').textContent=e.episode_id;get('position').textContent=(position+1)+' / '+entries.length;get('policy').textContent=e.policy;get('tools').textContent=JSON.stringify(e.agent_tools,null,2);get('transcript').replaceChildren();for(const m of e.transcript){const node=document.createElement('pre');node.className='message';node.textContent='index '+m.index+' | '+m.role+'\n'+(m.content||'')+(m.tool_calls.length?'\n'+JSON.stringify(m.tool_calls,null,2):'');get('transcript').appendChild(node);}const a=answers[e.episode_id]||{};for(const id of ids)get(id).value=a[id]||'';get('validation').textContent='';get('previous').disabled=position===0;get('next').disabled=position===entries.length-1;get('progress').textContent=Object.values(answers).filter(a=>a.category).length+'/'+entries.length+' 条已选类别';}
for(const id of ids)get(id).addEventListener('change',persist);
get('previous').onclick=()=>{persist();position--;render();};get('next').onclick=()=>{persist();position++;render();};
get('export').onclick=()=>{persist();const result=entries.map(e=>{const a=answers[e.episode_id]||{};return {episode_id:e.episode_id,category:a.category||null,decision_index:a.decision===''||a.decision===undefined?null:Number(a.decision),evidence:a.evidence||'',rationale:a.rationale||'',prior_exposure:a.exposure||null,wall_seconds:a.wall_seconds||0};});const invalid=result.filter(a=>['A','B','C','other'].includes(a.category)&&!entries.find(e=>e.episode_id===a.episode_id).transcript.some(m=>m.index===a.decision_index&&m.role==='assistant'));if(invalid.length){get('validation').textContent='请检查决策 index 必须对应 assistant：'+invalid.map(a=>a.episode_id).join(', ');return;}const blob=new Blob([JSON.stringify({annotation_type:'independent_human_candidate_review',created_at:new Date().toISOString(),entries:result},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='p4_human_annotations.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};render();
</script></html>"""
    (c.OUT / "annotation.html").write_text(template.replace("__DATA__", data))
    print("created blinded annotation packet", len(entries))


if __name__ == "__main__":
    main()
