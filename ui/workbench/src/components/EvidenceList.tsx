import { records, text, valueText } from '../facts';
import { CopyText, Fields } from './Facts';
const integrity: Record<string, string> = {
  match: '文件哈希匹配（不等于验收通过）', mismatch: '与该次引用的哈希不匹配',
  unavailable: '文件无法核对', not_recorded: '该次引用未记录哈希', not_checked: '锚点未确认，未核对',
};
export function EvidenceList({ value }: { value: unknown }) {
  const rows = records(value);
  if (!rows.length) return <p className="muted">未取得证据引用，不代表相关检查已经执行。</p>;
  return <div className="evidence-list"><p className="muted">按路径聚合 {rows.length} 项。每次引用单独保留哈希与来源；文件存在或哈希匹配不证明内容结论、当前主体和验收范围有效。</p>
    {rows.map((row, i) => <details key={`${text(row.anchor)}:${text(row.normalized_path)}:${i}`}>
      <summary>{text(row.display_name) || '未命名引用'} · {text(row.scope_label)} · {text(row.occurrence_count)} 次引用</summary>
      <CopyText value={row.copy_path} label="复制路径"/>
      <Fields value={{ anchor: row.anchor, current_exists: row.current_exists, inspection: row.inspection,
        current_sha256: row.current_sha256, inspection_error: row.inspection_error }}
        labels={{ anchor: '路径锚点', current_exists: '读取时文件存在', inspection: '文件读取状态', current_sha256: '本次文件哈希', inspection_error: '未核对原因' }}/>
      {records(row.sources).map((source, j) => <div className="evidence-source" key={`${text(source.event_id)}:${text(source.field)}:${j}`}>
        <strong>{integrity[text(source.integrity)] ?? valueText(source.integrity)}</strong>
        <CopyText value={source.event_id} label="复制事件 ID"/>
        <Fields value={source} labels={{ sha256: '该次引用原哈希', field: '来源字段', event_type: '事件类型', created_at: '记录时间', summary: '历史摘要（不作结论）' }}/>
      </div>)}
    </details>)}
  </div>;
}
