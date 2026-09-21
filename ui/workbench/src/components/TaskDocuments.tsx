import { record, records, text } from '../facts';
import { CopyText, Disclosure, Fields } from './Facts';

const labels: Record<string, string> = {
  CURRENT: '来源与正文摘要匹配', STALE: '过期，不作为当前接续',
  MISSING: '尚未生成', INVALID: '读取或格式异常', UNKNOWN: '新鲜度未确认',
};

/** References and projection health only; never renders copied canonical prose. */
export function TaskDocuments({ value }: { value: unknown }) {
  const data = record(value);
  if (!Object.keys(data).length)
    return <p className="support-note" role="status">任务文档新鲜度尚未读取，不把旧生成物视为当前事实。</p>;
  const views = records(data.views), nav = record(data.navigation);
  const selected = views.find(view => view.selected === true);
  return <section className="detail-section" aria-label="任务文档与历史导航">
    <h3>任务文档</h3>
    <p>{text(data.note)}</p>
    <p role="status">当前入口：<code>{text(data.selected_view) || '未确定'}</code> · {labels[text(selected?.status)] || '未确认'}</p>
    <Disclosure label="查看文档来源、过期原因与历史导航">
      <Fields value={{ state: data.state, state_source: data.state_source,
        current_roles: data.current_roles, next_responsibility: data.next_responsibility,
        quality: data.quality, quality_source: data.quality_source }}
        labels={{ state: '本次读取状态', state_source: '状态依据', current_roles: '当前角色（不代表在线）',
          next_responsibility: '下一责任（终态无后续动作）', quality: '已记录质量与提炼结果', quality_source: '质量结果解释边界' }}/>
      {views.map(view => <div className="record-block" key={text(view.path)}>
        <h4>{text(view.path)} · {labels[text(view.status)] || '未确认'}</h4>
        <Fields value={{ generated_at: view.generated_at, declared_state: view.declared_state, issues: view.issues }}
          labels={{ generated_at: '原生成时间', declared_state: '生成时状态', issues: '读取提示 / 过期依据' }}/>
      </div>)}
      <p>{text(nav.note)} 路径相对于任务目录；复制路径后在本地按需打开，不会在浏览器执行文件或命令。</p>
      {records(nav.references).map(ref => <p key={text(ref.path)}>{text(ref.label)}：<CopyText value={ref.path}/></p>)}
      <Fields value={{ current_region_status: nav.current_region_status, current_source: nav.current_source, issues: nav.issues }}
        labels={{ current_region_status: '唯一当前区读取状态', current_source: '范围正文来源', issues: '当前区提示' }}/>
      <p>{text(data.recovery)}</p>
    </Disclosure>
  </section>;
}
