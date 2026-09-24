import { useState, type ReactNode } from 'react';
import { Alert, Button, Card, Collapse, Descriptions, Empty as AntEmpty, Skeleton, Space, Tag, Typography } from 'antd';
import { explainValue, fieldLabel, record, records, timestampRaw, timestampText, valueText, text } from '../facts';
import type { Envelope, ReadState } from '../types';
export function Problems({ items = [] }: {
    items?: unknown;
}) {
    if (!Array.isArray(items))
        return <Alert type="warning" showIcon title="读取提示字段格式无法识别。"/>;
    const rows = records(items);
    if (!rows.length)
        return null;
    return <Alert className="problems" type="warning" showIcon title={`本次读取提示 · ${items.length}`}
    description={<ul>{rows.map((p, i) => <li key={`${p.code}:${i}`}><Typography.Text code>{valueText(p.code)}</Typography.Text> {valueText(p.message)}</li>)}</ul>}/>;
}
export function ReadStatus({ data, error, loading, showDetails = true }: ReadState<Envelope<unknown>> & { showDetails?: boolean }) {
    return <div className="read-status" aria-live="polite" aria-busy={loading}>
    {/* Static skeleton on purpose: `active` would be a looping pulse, which the workbench's motion
        rules forbid. The sentence moves into a visually-hidden copy so assistive technology still
        hears that a read is in progress. */}
    {loading && <div className="read-loading"><Skeleton active={false} title={false} paragraph={{ rows: 2 }}/><span className="visually-hidden">正在读取当前事实…</span></div>}
    {error && <Alert role="alert" type="error" showIcon title={`读取失败：${error}${data ? '。保留上次内容及原读取时间。' : ''}`}/>}
    {data && <Space size={8} wrap><Tag variant="filled" color={error || data.read.completeness === 'partial' ? 'warning' : undefined}>读取于 <time dateTime={data.read.completed_at} title={data.read.completed_at}>{timestampText(data.read.completed_at)}</time> · {error ? '上次读取快照' : loading ? '正在重新读取' : data.read.completeness === 'partial' ? '部分数据缺失' : '本次读取完成'}</Tag>
      {showDetails && <Collapse className="read-details" size="small" ghost items={[{ key: 'read', label: '读取说明与一致性边界', children: <div className="read-details-body">
        <p>{data.read.note}</p><p>一致性边界：<Typography.Text code>{data.read.consistency}</Typography.Text></p>
        {data.read.task_revision && <p>账本观察标识（不含文件原子性保证）：<CopyText value={data.read.task_revision}/></p>}
        {data.context && <Fields value={data.context} labels={{ context_key: '上下文键', project_id: '项目 ID', project_root: '项目根', workspace_root: '工作区', db_path: 'Runtime', source: '上下文来源', registry_path: '注册表' }}/>}
      </div>}]}/>}</Space>}
  </div>;
}
export function Empty({ title, children, action }: {
    title: string;
    children?: ReactNode;
    action?: ReactNode;
}) {
    return <div className="empty-state"><AntEmpty image={AntEmpty.PRESENTED_IMAGE_SIMPLE} description={<><strong>{title}</strong>{children && <span className="empty-body">{children}</span>}</>}/>{action}</div>;
}
export function Fields({ value, labels = {} }: {
    value: unknown;
    labels?: Record<string, string>;
}) {
    const source = record(value), entries = Object.entries(source);
    if (!entries.length)
        return <Typography.Text type="secondary">未记录</Typography.Text>;
    return <Descriptions className="fields" size="small" bordered column={1} items={entries.map(([key, item]) => ({
        key,
        label: <span title={key}>{fieldLabel(key, labels)}</span>,
        children: <FactValue name={key} value={item} declared={source[`${key}_declared`]}/>,
    }))}/>;
}
function FactValue({ name, value, declared }: {
    name: string;
    value: unknown;
    declared?: unknown;
}) {
    if (typeof value === 'object' && value !== null) {
        /* A single record renders its table straight away: it carries a handful of short facts, so the
           「展开字段」 click was a step with nothing behind it. A LIST stays folded — one response can
           carry dozens of records, and expanding every one inline would bury the rest of the page. */
        if (!Array.isArray(value))
            return <Fields value={value}/>;
        const rows: unknown[] = value;
        return <Collapse className="fact-nested" size="small" items={[{ key: name, label: `${rows.length} 条记录`, children: rows.length
            ? rows.map((item, i) => <div className="fact-record" key={i}><Typography.Text type="secondary">记录 {i + 1}</Typography.Text>
        {typeof item === 'object' && item !== null ? <Fields value={item}/> : <Typography.Text>{explainValue(name, item) || valueText(item)}</Typography.Text>}</div>) : <Typography.Text type="secondary">空列表</Typography.Text> }]}/>;
    }
    if (declared === false)
        return <Typography.Text className="fact-value">未声明</Typography.Text>;
    const raw = timestampRaw(value);
    return <Typography.Text className="fact-value" title={raw || undefined}>{explainValue(name, value) || timestampText(value)}</Typography.Text>;
}
/* Two shared shells so every section/disclosure keeps one shape and one heading level:
   `Section` keeps a real <h4> inside the card header instead of a class-only div. */
export function Section({ title, children }: {
    title: string;
    children: ReactNode;
}) {
    return <Card size="small" className="wb-section" title={<h4>{title}</h4>}>{children}</Card>;
}
export function Disclosure({ label, children, open = false, className }: {
    label: ReactNode;
    children: ReactNode;
    open?: boolean;
    className?: string;
}) {
    return <Collapse className={className ? `wb-disclosure ${className}` : 'wb-disclosure'} size="small" defaultActiveKey={open ? ['content'] : undefined} items={[{ key: 'content', label, children }]}/>;
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
        // Ant Design's own `copyable` cannot report a failed write; keep the explicit failure state.
        setStatus('复制失败，请手动选择文本');
    } }
    return <span className="copy-text"><Typography.Text code>{raw || '未记录'}</Typography.Text>{raw && <Button size="small" type="text" onClick={copy}>{label}</Button>}<Typography.Text type="secondary" role="status">{status}</Typography.Text></span>;
}
