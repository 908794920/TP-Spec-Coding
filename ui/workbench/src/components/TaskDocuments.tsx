import { record, records, stateLabel, text } from '../facts';
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
  const database = record(data.database_diagnostics);
  const hasDatabase = records(database.observations).length > 0
    || (Array.isArray(database.issues) && database.issues.length > 0)
    || (Array.isArray(database.unavailable_references) && database.unavailable_references.length > 0);
  const selected = views.find(view => view.selected === true);
  return <section className="detail-section" aria-label="任务文档与历史导航">
    <h3>任务文档</h3>
    {data.retired === true && <p role="status">已退休 · 最后正式工作流状态：{stateLabel('task', data.last_workflow_state)}</p>}
    <p>{text(data.note)}</p>
    <p role="status">当前入口：<code>{text(data.selected_view) || '未确定'}</code> · {labels[text(selected?.status)] || '未确认'}</p>
    <Disclosure label="查看文档来源、过期原因与历史导航">
      <Fields value={{ state: data.state, state_source: data.state_source,
        current_roles: data.current_roles, next_responsibility: data.next_responsibility,
        quality: data.quality, quality_source: data.quality_source,
        ...(data.retired === true ? { retirement: data.retirement, retirement_status: data.retirement_status } : {}) }}
        labels={{ state: '本次读取状态', state_source: '状态依据', current_roles: '当前角色（不代表在线）',
          next_responsibility: '下一责任（终态无后续动作）', quality: '已记录质量与提炼结果', quality_source: '质量结果解释边界' }}/>
      {views.map(view => <div className="record-block" key={text(view.path)}>
        <h4>{text(view.path)} · {labels[text(view.status)] || '未确认'}</h4>
        <Fields value={{ generated_at: view.generated_at, declared_state: view.declared_state, issues: view.issues }}
          labels={{ generated_at: '原生成时间', declared_state: '生成时状态', issues: '读取提示 / 过期依据' }}/>
      </div>)}
      <p>{text(nav.note)} 路径相对于任务目录；复制路径后在本地按需打开，不会在浏览器执行文件或命令。</p>
      {records(nav.references).map(ref => <p key={text(ref.path)}>{text(ref.label)}：<CopyText value={ref.path}/></p>)}
      {records(nav.archive_doc_links).map(ref => <div key={`${text(ref.source_path)}:${text(ref.source_line)}:${text(ref.path)}`}>
        <p>已核实归档资料 · {text(ref.label)}：<CopyText value={ref.resolved_target}/></p>
        <Fields value={{ source_path: ref.source_path, source_line: ref.source_line, original_target: ref.original_target }}
          labels={{ source_path: '原引用文档', source_line: '原引用行', original_target: '保留的历史引用' }}/>
      </div>)}
      <Fields value={{ current_region_status: nav.current_region_status, current_source: nav.current_source, issues: nav.issues }}
        labels={{ current_region_status: '唯一当前区读取状态', current_source: '范围正文来源', issues: '当前区提示' }}/>
      {!!records(nav.consistency_diagnostics).length && <Disclosure label="当前文字与正式状态的差异">
        <Fields value={{ observations: nav.consistency_diagnostics }}/>
      </Disclosure>}
      {hasDatabase && <Disclosure label="数据库已执行回执与声明对照（只读提示）">
        <Fields value={database}/>
      </Disclosure>}
      {!!data.terminal_integrity && <Disclosure label="原封存清单与当前文件对照">
        <Fields value={data.terminal_integrity} labels={{ added: '清单外新增', modified: '清单内已修改', deleted: '清单内已删除',
          change_kind: '实际差异类别', note: '历史证据解释边界' }}/>
      </Disclosure>}
      <p>{text(data.recovery)}</p>
    </Disclosure>
  </section>;
}
