import { useState, type ReactNode } from 'react';
import { record, records, valueText, text } from '../facts';
import type { Envelope, ReadState } from '../types';
export function Problems({ items = [] }: {
    items?: unknown;
}) {
    if (!Array.isArray(items)) return <p className="warning">读取提示字段格式无法识别。</p>;
    const rows = records(items);
    return rows.length ? <details className="problems" open><summary>本次读取提示 · {items.length}</summary>
    <ul>{rows.map((p, i) => <li key={`${p.code}:${i}`}><code>{valueText(p.code)}</code> {valueText(p.message)}</li>)}</ul></details> : null;
}
export function ReadStatus({ data, error, loading }: ReadState<Envelope<unknown>>) {
    return <div className="read-status" aria-live="polite" aria-busy={loading}>
    {loading && <span>正在读取当前事实… </span>}
    {error && <p className="error" role="alert">读取失败：{error}{data ? '。保留上次内容及原读取时间。' : ''}</p>}
    {data && <details><summary>读取于 <time dateTime={data.read.completed_at}>{data.read.completed_at}</time> · {data.read.completeness === 'partial' ? '部分数据缺失' : '本次读取完成'}</summary>
      <p>{data.read.note}</p><p>一致性边界：<code>{data.read.consistency}</code></p>
      {data.read.task_revision && <p>账本观察标识（不含文件原子性保证）：<CopyText value={data.read.task_revision}/></p>}
      {data.context && <Fields value={data.context} labels={{ context_key: '上下文键', project_id: '项目 ID', project_root: '项目根', workspace_root: '工作区', db_path: 'Runtime', source: '上下文来源', registry_path: '注册表' }}/>}
    </details>}
  </div>;
}
export function Empty({ title, children }: {
    title: string;
    children?: ReactNode;
}) {
    return <div className="empty-state"><h3>{title}</h3>{children && <p>{children}</p>}</div>;
}
export function Fields({ value, labels = {} }: {
    value: unknown;
    labels?: Record<string, string>;
}) {
    const entries = Object.entries(record(value));
    if (!entries.length)
        return <p className="muted">未记录</p>;
    return <dl className="fields">{entries.map(([key, val]) => <div className="field" key={key}>
    <dt>{labels[key] ?? key}</dt><dd>{typeof val === 'object' && val !== null
                ? <details><summary>{Array.isArray(val) ? `${val.length} 条记录` : '展开字段'}</summary>
        {Array.isArray(val) ? val.length ? val.map((v, i) => <div className="array-record" key={i}><span className="muted">记录 {i + 1}</span>{typeof v === 'object' && v !== null ? <Fields value={v}/> : <span>{valueText(v)}</span>}</div>) : <p>空列表</p> : <Fields value={val}/>}</details>
                : <span className="fact-value">{record(value)[`${key}_declared`] === false ? '未声明' : valueText(val)}</span>}</dd>
  </div>)}</dl>;
}
export function CopyText({ value, label = '复制' }: {
    value: unknown;
    label?: string;
}) {
    const [status, setStatus] = useState('');
    const raw = text(value);
    async function copy() { try {
        if (!navigator.clipboard)
            throw new Error('当前浏览器不支持剪贴板 API');
        await navigator.clipboard.writeText(raw);
        setStatus('已复制');
    }
    catch {
        setStatus('复制失败，请手动选择文本');
    } }
    return <span className="copy-text"><code>{raw || '未记录'}</code>{raw && <button type="button" className="quiet" onClick={copy}>{label}</button>}<span role="status">{status}</span></span>;
}
