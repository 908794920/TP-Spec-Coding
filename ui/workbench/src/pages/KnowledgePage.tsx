import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Alert, Button, Card, Checkbox, Drawer, Input, Pagination, Segmented, Select, Space, Tabs, Tag } from 'antd';
import { ArrowLeftOutlined, DatabaseOutlined, FileSearchOutlined, ReadOutlined, SearchOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import type { Root } from 'mdast';
import rehypeSlug from 'rehype-slug';
import remarkGfm from 'remark-gfm';
import { Empty as WorkbenchEmpty, Problems, ReadStatus } from '../components/Facts';
import { timestampText } from '../facts';
import { useRead } from '../useRead';
import { knowledgeApi } from '../knowledgeApi';
import type { ReadState } from '../types';
import type { KnowledgeCollection, KnowledgeDocument, KnowledgeDocuments, KnowledgeEnvelope,
    KnowledgeOverview, KnowledgeProject, KnowledgePurpose, KnowledgeRecord, KnowledgeRecordQuery, KnowledgeDocumentData,
    KnowledgeRecords, KnowledgeScope, KnowledgeDays, KnowledgeRecordStatus } from '../knowledgeTypes';
import '../styles/wiki.css';
import '../styles/knowledge.css';

const purposes: { value: KnowledgePurpose; label: string }[] = [
    { value: 'development', label: 'AI 研发使用' }, { value: 'delivery_convergence', label: '交付收敛检索' },
    { value: 'maintenance', label: '维护' }, { value: 'unknown', label: '未知用途 / 旧记录' }, { value: 'all', label: '全部用途' },
];
const statuses: { value: KnowledgeRecordStatus; label: string }[] = [
    { value: 'all', label: '全部' }, { value: 'hit', label: '有结果' }, { value: 'zero', label: '零结果' }, { value: 'failed', label: '执行失败' },
];
const labels: Record<string, string> = { available: '可用', partial: '部分可用', missing: '数据库缺失',
    unavailable: '读取失败 / 不可用', legacy: '旧采集契约', not_collected: '未接入采集', disabled: '采集已关闭',
    completed: '完成', failed: '执行失败', historical: '历史未记录', same: '与当前一致', changed: '版本已变化',
    boundary_rejected: '路径边界已变化', indexed: '已索引', metadata_only: '仅登记元数据', unknown: '未知', stale: '已记录过期', expired: '已过期', outdated: '已记录过期', conflict: '已记录冲突',
    superseded: '已被替代', missing_evidence: '缺少已记录来源证据', zero: '连续零结果', unadopted: '尚无已记录采用',
};
const label = (status: string | undefined): string => labels[status || ''] || status || '未记录';
function Empty({ children }: { children: ReactNode }) { return <WorkbenchEmpty title="">{children}</WorkbenchEmpty>; }
const purposeLabel = (purpose: string) => purposes.find(p => p.value === purpose)?.label || '未知用途';
const num = (value: number | null | undefined) => value === null || value === undefined ? '—' : value.toLocaleString('zh-CN');
const date = (value: string | null | undefined) => value ? timestampText(value) : '—';
const printable = (value: unknown): string => typeof value === 'string' ? value : value === null || value === undefined ? '未记录' : JSON.stringify(value);
type KRead<T> = ReadState<KnowledgeEnvelope<T>>;
type Tab = 'overview' | 'documents' | 'records';
type MarkdownNode = { type: string; value?: string; url?: string; children?: MarkdownNode[] };

function registeredWikiLinks(links: KnowledgeDocumentData['links']) {
    const known = new Map(links.map(link => [link.href, link]));
    return () => (tree: Root) => {
        function visit(node: MarkdownNode) {
            if (!node.children || node.type === 'link' || node.type === 'linkReference') return;
            node.children = node.children.flatMap(child => {
                if (child.type !== 'text' || !child.value?.includes('[[')) { visit(child); return [child]; }
                const parts: MarkdownNode[] = [];
                let cursor = 0;
                for (const match of child.value.matchAll(/\[\[([^\]\r\n]+)\]\]/g)) {
                    const inner = match[1], separator = inner.indexOf('|');
                    const href = separator < 0 ? inner : inner.slice(0, separator);
                    const target = known.get(href);
                    if (!target) continue;
                    const start = match.index ?? 0;
                    if (start > cursor) parts.push({ type: 'text', value: child.value.slice(cursor, start) });
                    const title = separator < 0 ? '' : inner.slice(separator + 1).trim();
                    parts.push({ type: 'link', url: href, children: [{ type: 'text', value: title || target.title || href }] });
                    cursor = start + match[0].length;
                }
                if (!parts.length) return [child];
                if (cursor < child.value.length) parts.push({ type: 'text', value: child.value.slice(cursor) });
                return parts;
            });
        }
        visit(tree as unknown as MarkdownNode);
    };
}

function Collection({ title, value }: { title: string; value: KnowledgeCollection }) {
    return <Card size="small" className="knowledge-collection" title={title} extra={<Tag>{label(value.status)}</Tag>}>
      <p>采集起点：{date(value.started_at)}<br/>已知范围内最近记录：{date(value.recent_at)}</p>
      <p className="muted">{value.note}</p>
      {value.window_complete === false && <p className="knowledge-warning">所选时间窗未证实完整覆盖；数字仅代表已保留的记录。</p>}
      <details><summary>可用范围与实际保留范围</summary>
        <p>可用：{value.available_projects.join('、') || '无已确认范围'}</p>
        <p>缺失：{value.missing_projects.join('、') || '无已知缺失'}{value.unresolved_contexts?.length ? `；未解析：${value.unresolved_contexts.join('、')}` : ''}</p>
        {value.sources.map((source, index) => <div className="knowledge-source-state" key={source.database_id || source.project_key || index}>
          <strong>{source.name || source.source_id || '来源'} · {label(source.status)}</strong>
          <span>采集开始：{date(source.started_at)}</span>
          {source.retention_days !== undefined && <><span>配置保留：{source.retention_days} 天；可比口径起点：{date(source.coverage_start)}</span>
            <span>现存记录范围：{date(source.earliest_retained_at)} — {date(source.latest_retained_at)}</span></>}
          {source.note && <small>{source.note}</small>}
        </div>)}
        {!!value.unmapped_assets && <p>无法唯一关联当前文档的历史资产：{value.unmapped_assets}。保留采用事实，不猜测链接。</p>}
      </details>
    </Card>;
}

function DocumentRow({ doc, onOpen }: { doc: KnowledgeDocument; onOpen: (key: string) => void }) {
    return <li className="knowledge-document-row"><button type="button" onClick={() => onOpen(doc.key)}>
      <span className="knowledge-document-title"><strong title={doc.title || doc.id || doc.path}>{doc.title || doc.id || doc.path}</strong>
        <small>{doc.id || '无 legacy ID'} · {doc.path}</small>{doc.snippet && <small className="wiki-document-snippet">{doc.snippet}</small>}</span>
      <span><Tag>{doc.layer === 'canonical' ? '长期知识' : '来源资料'}</Tag><small>{doc.kind || '类型未记录'}</small>{doc.availability && !['indexed', 'available'].includes(doc.availability) && <small>{label(doc.availability)}</small>}</span>
      <span className="knowledge-document-scope">{doc.project_name || doc.project}<small>{doc.status ? label(doc.status) : '维护状态未记录'}</small></span>
      <span className="knowledge-document-counts">读取 {num(doc.reads)} · 采用任务 {num(doc.adopted_tasks)}<small>更新 {date(doc.updated_at)}</small></span>
    </button></li>;
}

function Pages({ total, page, onChange }: { total: number | null; page: number; onChange: (page: number) => void }) {
    return <div className="wiki-pagination"><span className="muted">已知 {num(total)} 条 · 每页 20 条</span>
      <Pagination current={page} pageSize={20} total={total ?? 0} showSizeChanger={false} onChange={onChange} size="small" hideOnSinglePage/></div>;
}

function Overview({ read, open, chooseProject, showRecords, showAdopted }: {
    read: KRead<KnowledgeOverview>; open: (key: string) => void; chooseProject: (key: string) => void;
    showRecords: (status?: KnowledgeRecordStatus, date?: string, hash?: string) => void; showAdopted: () => void;
}) {
    const data = read.data?.data;
    if (!data) return <ReadStatus {...read}/>;
    const metrics = data.metrics;
    return <div className="wiki-tab-body"><ReadStatus {...read}/><Problems items={data.problems}/>
      <div className="wiki-two-columns"><Collection title="检索 / 读取日志状态" value={data.collection}/><Collection title="任务采用记录状态" value={data.adoption_collection}/></div>
      <p className="muted">{data.statistics_note}</p>
      <div className="wiki-metrics-grid">
        {[{ title: '已识别 AI 搜索', value: num(metrics.searches), note: '完成搜索；含成功零结果', action: () => showRecords() },
          { title: '有结果占比', value: metrics.hit_rate === null ? '—' : `${(metrics.hit_rate * 100).toFixed(1)}%`, note: '有去重文档 / 完成搜索', action: () => showRecords('hit') },
          { title: '已记录采用任务', value: num(metrics.adopted_tasks), note: '独立可信采用；不按检索用途过滤', action: showAdopted },
          { title: '已记录采用条目', value: num(metrics.adopted_documents), note: '可信资产去重；未关联事实仍保留', action: showAdopted }].map(metric =>
          <button type="button" key={metric.title} className="wiki-metric" onClick={metric.action}><span className="wiki-metric-copy">
            <span className="wiki-metric-label">{metric.title}</span><strong>{metric.value}</strong><small>{metric.note}</small></span></button>)}
      </div>
      <Card size="small" className="wiki-section-card" title="已知范围内最近活动"><div className="knowledge-recent">
        {(['search', 'read', 'adopted'] as const).map(key => <div key={key}><strong>{{ search: '最近成功搜索', read: '最近正文读取', adopted: '最近采用' }[key]}</strong>
          <time>{date(data.recent_activity[key].at)}</time><small>{label(data.recent_activity[key].status)}</small></div>)}
      </div><p className="muted">真实正文读取 {num(metrics.reads)} 次；执行失败 {num(metrics.failures)} 次。失败不计入零结果，也不更新最近成功搜索。</p></Card>
      <Card size="small" className="wiki-section-card" title="检索层级与历史口径">
        <p>含 canonical 结果 {num(metrics.canonical_searches)} 次 · 含 source 结果 {num(metrics.source_searches)} 次。二者可重叠，不是互斥占比。</p>
        <p>已记录补充原因：{Object.entries(metrics.fallback_reasons).map(([reason, count]) => `${reason}（${count}）`).join('、') || '无已记录原因'}。显式 source 查询不意味着 canonical 失败。</p>
        <p className="muted">{data.history.note} 全局历史未归因：{num(data.history.count)}；新契约但未识别来源：{data.unidentified_searches}。</p>
      </Card>
      <div className="wiki-two-columns knowledge-usage-grid"><Card size="small" title="日趋势 · UTC+8 日期">
        <div className="knowledge-table-wrap knowledge-usage-table"><table><thead><tr><th>日期</th><th>完成搜索</th><th>有结果</th><th>采用任务</th></tr></thead><tbody>
          {data.trend.map(row => <tr key={row.date}><th><button type="button" className="knowledge-link" onClick={() => showRecords('all', row.date)}>{row.date}</button></th>
            <td>{num(row.searches)}</td><td>{num(row.hits)}</td><td>{num(row.adopted_tasks)}</td></tr>)}
        </tbody></table></div><p className="muted">“—”为未证实覆盖或无样本，不补成零；时间窗首尾可能不足整天。</p>
      </Card><Card size="small" title="项目使用 · 按请求项目归因">
        {data.project_usage.length ? <div className="knowledge-table-wrap knowledge-usage-table"><table><thead><tr><th>请求项目</th><th>搜索</th><th>正文读取</th><th>采用任务</th></tr></thead><tbody>
          {data.project_usage.map(row => <tr key={row.key}><th><button type="button" className="knowledge-link" onClick={() => chooseProject(row.key)}>{row.name}</button></th>
            <td>{num(row.searches)}</td><td>{num(row.reads)}</td><td>{num(row.adopted_tasks)}</td></tr>)}
        </tbody></table></div> : <Empty>所选范围没有可列出的业务项目。</Empty>}
        <p className="muted">共享内容不冒充业务项目私有内容；未归因历史不分摊给项目。</p>
      </Card></div>
      <Card size="small" className="wiki-section-card" title="常用条目">{data.popular.length ? <ul className="knowledge-document-list">{data.popular.map(doc => <DocumentRow key={doc.key} doc={doc} onOpen={open}/>)}</ul> : <Empty>尚无可关联的正文读取或采用条目；不代表知识无价值。</Empty>}</Card>
      <Card size="small" className="wiki-section-card" title="待关注内容 · 仅已有事实">{data.attention.length ? <ul className="knowledge-attention">{data.attention.map((item, index) => <li key={`${item.document_key || item.query_hash}-${index}`}>
        <Tag>{label(item.kind)}</Tag><button type="button" className="knowledge-link" onClick={() => item.document_key ? open(item.document_key) : showRecords('zero', '', item.query_hash)}>{item.title}</button>
        {item.count && <span> · {item.count} 次；未保存搜索原文</span>}</li>)}</ul> : <Empty>当前已知范围没有这些事实，不代表所有内容都已校验。</Empty>}</Card>
      <Card size="small" className="wiki-section-card" title="内容与维护摘要" extra={<Tag>{label(data.maintenance.status)}</Tag>}>
        <p>canonical 条目 {num(data.maintenance.canonical_documents)} · source 文档 {num(data.maintenance.source_documents)} · 已注册来源文件 {num(data.maintenance.registered_sources)}</p>
        {data.maintenance.sources.map(source => <details key={source.source_id}><summary>来源 {source.source_id} · {label(source.status)} · 索引更新 {date(source.indexed_at)}</summary>
          {source.reports.length ? source.reports.map(report => <p key={report.name}>{report.name} · {printable(report.status)} · 报告时间 {date(report.at)} · 文件更新时间 {date(report.file_updated_at)}<br/><small>{report.note}</small></p>) : <p className="muted">没有已记录维护报告；打开页面不会触发校验或维护。</p>}
        </details>)}
      </Card>
    </div>;
}

function RecordItem({ row, scope, revision, open }: { row: KnowledgeRecord; scope: KnowledgeRecordQuery; revision: number; open: (key: string) => void }) {
    const [expanded, setExpanded] = useState(false);
    const detail = useRead(expanded ? JSON.stringify([scope, row.key]) : '', revision, signal => knowledgeApi.records({ ...scope, receipt: row.key, page: 1 }, signal));
    const result = detail.data?.data.items[0];
    return <li className="wiki-record-row"><details onToggle={event => setExpanded(event.currentTarget.open)}>
      <summary><span className="wiki-record-status"><Tag>{row.historical ? '旧记录' : row.status === 'failed' ? '执行失败' : row.document_count ? '有结果' : '零结果'}</Tag><strong title={row.query_hash}>{row.query_hash.slice(0, 12) || '哈希未记录'}</strong></span>
        <span>{row.project_name}</span><span>{row.historical ? '历史身份未记录' : `${row.task_id || '未提供 Task'} · ${row.actor_role || '未提供角色'}`}</span><time>{date(row.created_at)}</time></summary>
      {expanded && <div className="wiki-record-detail"><div className="wiki-record-meta">
        <span>执行时间：{date(row.created_at)}</span><span>用途：{purposeLabel(row.purpose)}</span><span>调用来源：{row.historical ? '历史未记录' : row.caller}</span>
        <span>请求范围：{row.historical ? '历史未归因' : `${row.request_scope} · ${row.requested_projects.join('、') || '未返回项目范围'}`}</span>
        <span>实际返回范围：{row.historical ? '历史未记录' : row.returned_projects.join('、') || '无返回文档'}</span>
        <span>去重文档：{num(row.document_count)}{row.historical ? `；旧片段计数 ${row.candidate_count}（不是文档数）` : ''}</span>
        <span>层级：{row.layer || '无结果或未记录'}</span><span>耗时：{num(row.elapsed_ms)} ms</span>
        <span>回执：{row.receipt_id || '历史未记录'}</span>{row.fallback_reason && <span>补充原因：{row.fallback_reason}</span>}{row.error_code && <span>错误：{row.error_code}</span>}
      </div><ReadStatus {...detail}/>{result && <div className="knowledge-record-results">
        {result.results === null || result.results === undefined ? <p className="muted">历史未记录结果列表，不能使用当前检索补造旧回执。</p> : result.results.length === 0 ? <p className="muted">此回执无返回文档。</p> : result.results.map((hit, index) =>
          <div key={`${hit.document_key || hit.id}-${index}`}><strong>{hit.key ? <button type="button" className="knowledge-link" onClick={() => open(hit.key!)}>{hit.title || hit.id || hit.path}</button> : hit.title || hit.id || hit.path || '未关联条目'}</strong>
            <small>{hit.layer} · {hit.project} · {hit.path}</small><span>{hit.version_kind === 'chunk' ? '片段版本（不是整篇）' : hit.version_kind === 'document' ? '整篇版本' : '已登记版本'} · {label(hit.version_status)}</span>
            <code>当时：{hit.version || '历史未记录'}</code><code>当前：{hit.current_version || '不可用 / 未记录'}</code>
          </div>)}
      </div>}</div>}
    </details></li>;
}

function DocumentReader({ keys, scope, revision, close, back, open, restore }: {
    keys: string[]; scope: KnowledgeScope; revision: number; close: () => void; back: () => void; open: (key: string) => void; restore: () => void;
}) {
    const key = keys.at(-1) || '';
    const read = useRead(key ? JSON.stringify([key, scope.days, scope.purpose]) : '', revision, signal => knowledgeApi.document(key, scope, signal));
    const data = read.data?.data, markdown = useRef<HTMLDivElement>(null);
    const [headings, setHeadings] = useState<{ id: string; title: string; level: number }[]>([]);
    useLayoutEffect(() => {
        setHeadings(Array.from(markdown.current?.querySelectorAll('h1,h2,h3,h4,h5,h6') || []).map(node => ({ id: node.id, title: node.textContent || '', level: Number(node.tagName.slice(1)) })));
    }, [data]);
    function jump(id: string) {
        const heading = Array.from(markdown.current?.querySelectorAll<HTMLElement>('[id]') || []).find(node => node.id === id);
        if (heading) { heading.scrollIntoView({ block: 'start' }); heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
    }
    return <Drawer className="wiki-document-drawer knowledge-reader" title="知识阅读" open={!!key} width={1000} onClose={close}
      afterOpenChange={isOpen => { if (!isOpen) restore(); }} keyboard destroyOnHidden
      extra={<Button icon={<ArrowLeftOutlined/>} disabled={keys.length < 2} onClick={back}>返回上篇</Button>}>
      <ReadStatus {...read}/>{data && <><Problems items={data.problems}/><div className="wiki-document-heading"><div><h2>{data.document.title || data.document.id || data.document.path}</h2>
        <span className="muted">{data.document.project_name || data.document.project} · {data.document.kind || '类型未记录'}</span></div>
        <Space wrap><Tag>{data.document.layer === 'canonical' ? '长期知识' : '来源资料 · 非已确认规则'}</Tag>{data.document.status && <Tag>{label(data.document.status)}</Tag>}<Tag>{label(data.document.version_status)}</Tag></Space></div>
        {data.document.metadata_only && <Alert type="info" showIcon title="来源原件未登记可读 Markdown；只展示已有元数据，不在线转换或抓取原件。"/>}
        <div className="wiki-document-layout"><aside className="wiki-toc"><strong>文档目录</strong>
          {headings.length ? <ol>{headings.map(heading => <li key={heading.id} className={`wiki-toc-level-${Math.min(heading.level, 3)}`}><button className="knowledge-link" type="button" onClick={() => jump(heading.id)}>{heading.title}</button></li>)}</ol> : <span className="muted">无可用标题</span>}
          <div className="wiki-source-box"><strong>来源与版本</strong><span>{data.document.id || '无 legacy ID'}</span><code>{data.document.key}</code><code>{data.document.path}</code>
            <span>更新时间 {date(data.document.updated_at)}</span><span>当前版本</span><code>{data.document.version || '未记录'}</code>
            {data.document.indexed_version && <><span>索引版本</span><code>{data.document.indexed_version}</code></>}
            {data.document.origin && <><strong>已登记原件元数据</strong><code>{printable(data.document.origin)}</code></>}
            {data.document.superseded !== null && <span>superseded：{printable(data.document.superseded)}</span>}
            {data.document.replaced_by !== null && <span>replaced_by：{printable(data.document.replaced_by)}</span>}
          </div></aside><article><div ref={markdown} className="wiki-markdown">
            {data.content ? <ReactMarkdown skipHtml remarkPlugins={[remarkGfm, registeredWikiLinks(data.links)]} rehypePlugins={[rehypeSlug]} components={{
                img: ({ alt }) => <span className="wiki-image-placeholder">图片未自动加载：{alt || '未提供说明'}</span>,
                a: ({ href, children }) => {
                    let decoded = href;
                    try { decoded = decodeURIComponent(href || ''); } catch { /* malformed link remains inert */ }
                    const internal = data.links.find(link => link.href === href || link.href === decoded);
                    if (internal) return <button type="button" className="knowledge-link" onClick={() => open(internal.key)}>{children}</button>;
                    if (href?.startsWith('#')) return <button type="button" className="knowledge-link" onClick={() => { try { jump(decodeURIComponent(href.slice(1))); } catch { /* malformed fragment remains inert */ } }}>{children}</button>;
                    if (href && /^https?:\/\//i.test(href)) {
                        try { const target = new URL(href); return <a href={target.href} rel="noopener noreferrer" target="_blank">{children}<small className="knowledge-external">（{target.host}）</small></a>; }
                        catch { /* invalid external link is plain content */ }
                    }
                    return <span className="wiki-unregistered-link" title="非已注册知识文档或不支持的链接">{children}</span>;
                },
            }}>{data.content}</ReactMarkdown> : <Empty>{data.document.metadata_only ? '仅已有来源元数据。' : '正文为空。'}</Empty>}
          </div><p className="muted">页面显示当前完整正文；不受 CLI 预览预算限制，也不增加 AI 正文读取次数。</p>
          <section className="wiki-document-links"><h3>来源、证据与局部关联</h3>
            <ul>{data.links.map(link => <li key={link.href}><button type="button" onClick={() => open(link.key)}>{link.title || link.href}</button><code>{link.href}</code></li>)}
              {data.references.map((reference, index) => <li key={index}><span>{reference.kind}：{reference.key ? <button type="button" onClick={() => open(reference.key!)}>{reference.title || printable(reference.ref)}</button> : printable(reference.ref)}</span><small>{reference.key ? '已注册条目' : '未关联；不猜测链接'}</small></li>)}
              {data.document.evidence_refs.map((evidence, index) => <li key={`evidence-${index}`}><span>证据</span><code>{printable(evidence)}</code></li>)}
            </ul>{!data.links.length && !data.references.length && !data.document.evidence_refs.length && <p className="muted">未记录可展示的局部关联或来源证据。</p>}
          </section><section className="wiki-document-usage-section"><h3>关联使用记录 · 全部已知请求项目</h3>
            <p className="muted">检索/读取日志：{label(data.collection.status)}；采用记录：{label(data.adoption_collection.status)}。采用无需历史回执也可作为独立事实。</p>
            {data.usage.length ? <ul className="wiki-document-usage">{data.usage.map((usage, index) => <li key={index}><Tag>{usage.stage === 'adopted' ? '已记录采用' : usage.stage === 'read' ? '正文读取' : usage.stage}</Tag>
              <span>{usage.task_id || '未提供 Task'}<small>{usage.project_name} · {usage.actor_role || '角色未记录'}{usage.purpose ? ` · ${purposeLabel(usage.purpose)}` : ''}</small></span><time>{date(usage.created_at)}</time><code>{usage.receipt_id || '无历史回执关联'}</code></li>)}</ul> : <p className="muted">所选时间窗没有可关联记录；不可用范围不能视为零采用。</p>}
          </section></article></div></>}
    </Drawer>;
}

export function KnowledgePage({ revision }: { revision: number }) {
    const [tab, setTab] = useState<Tab>('overview'), [scope, setScope] = useState<KnowledgeScope>({ project: '', days: 30, purpose: 'development' });
    const [projects, setProjects] = useState<KnowledgeProject[]>([]), [keys, setKeys] = useState<string[]>([]);
    const entryFocus = useRef<HTMLElement | null>(null), heading = useRef<HTMLHeadingElement>(null);
    const [q, setQ] = useState(''), [query, setQuery] = useState(''), [layer, setLayer] = useState(''), [kind, setKind] = useState(''), [maintenance, setMaintenance] = useState(''), [adopted, setAdopted] = useState(false), [page, setPage] = useState(1);
    const [recordPage, setRecordPage] = useState(1), [recordStatus, setRecordStatus] = useState<KnowledgeRecordStatus>('all');
    const [taskInput, setTaskInput] = useState(''), [hashInput, setHashInput] = useState(''), [dateInput, setDateInput] = useState('');
    const [recordFilter, setRecordFilter] = useState({ task: '', hash: '', date: '' });
    const overview = useRead(tab === 'overview' ? JSON.stringify(['knowledge-overview', scope]) : '', revision, signal => knowledgeApi.overview(scope, signal));
    const docQuery = { ...scope, page, q: query, layer, kind, maintenance, adopted };
    const docs = useRead(tab === 'documents' ? JSON.stringify(['knowledge-documents', docQuery]) : '', revision, signal => knowledgeApi.documents(docQuery, signal));
    const recordsQuery: KnowledgeRecordQuery = { ...scope, ...recordFilter, page: recordPage, status: recordStatus };
    const records = useRead(tab === 'records' ? JSON.stringify(['knowledge-records', recordsQuery]) : '', revision, signal => knowledgeApi.records(recordsQuery, signal));
    useEffect(() => {
        const available = overview.data?.data.projects || docs.data?.data.projects || records.data?.data.projects;
        if (available) setProjects(available);
    }, [overview.data, docs.data, records.data]);
    function changeScope(next: Partial<KnowledgeScope>) { setScope(previous => ({ ...previous, ...next })); setPage(1); setRecordPage(1); }
    function open(key: string) {
        if (!keys.length) entryFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setKeys(previous => previous.at(-1) === key ? previous : [...previous, key]);
    }
    function showRecords(status: KnowledgeRecordStatus = 'all', day = '', hash = '') {
        setRecordStatus(status); setRecordFilter({ task: '', hash, date: day }); setTaskInput(''); setHashInput(hash); setDateInput(day); setRecordPage(1); setTab('records');
    }
    const documentsData: KnowledgeDocuments | undefined = docs.data?.data;
    const recordsData: KnowledgeRecords | undefined = records.data?.data;
    function searchDocuments(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setQuery(q.trim()); setPage(1); }
    function searchRecords(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setRecordFilter({ task: taskInput.trim(), hash: hashInput.trim(), date: dateInput }); setRecordPage(1); }
    const documentTab = <div className="wiki-tab-body"><Card size="small" className="wiki-filter-card knowledge-filter-card">
      <form className="wiki-filter-form" onSubmit={searchDocuments}>
        <label className="wiki-query-field"><span>标题 / ID / 路径 / 正文</span><Input value={q} maxLength={512} allowClear onChange={event => setQ(event.target.value)} placeholder="查找当前范围的知识" aria-label="知识搜索"/></label>
        <label><span>层级</span><Select value={layer} onChange={value => { setLayer(value); setPage(1); }} options={[{ value: '', label: '全部层级' }, { value: 'canonical', label: '长期知识 canonical' }, { value: 'source', label: '来源资料 source' }]}/></label>
        <label><span>类型</span><Select value={kind} onChange={value => { setKind(value); setPage(1); }} options={[{ value: '', label: '全部类型' }, ...(documentsData?.kinds || []).map(value => ({ value, label: value }))]}/></label>
        <label><span>已记录维护状态</span><Select value={maintenance} onChange={value => { setMaintenance(value); setPage(1); }} options={[{ value: '', label: '全部状态' }, ...(documentsData?.maintenance_states || []).map(value => ({ value, label: label(value) }))]}/></label>
        <Checkbox checked={adopted} onChange={event => { setAdopted(event.target.checked); setPage(1); }}>仅已记录采用</Checkbox><Button htmlType="submit" icon={<SearchOutlined/>}>查找</Button>
      </form><p className="wiki-filter-note knowledge-filter-note">人工搜索只查所选内容范围，不新增 AI 使用次数。文档集合不按使用时间缩减；读取次数按用途，采用是独立事实。shared 以共享范围展示。</p>
    </Card><ReadStatus {...docs}/>{documentsData && <><Problems items={documentsData.problems}/>
      {documentsData.status !== 'available' && <Alert type="warning" showIcon title={`${label(documentsData.status)}：不能把未取得的来源当作零结果。`}/>}
      {documentsData.items.length ? <ul className="knowledge-document-list">{documentsData.items.map(doc => <DocumentRow key={doc.key} doc={doc} onOpen={open}/>)}</ul> : documentsData.status === 'available' ? <Empty>所选范围与筛选条件下没有匹配的文档。</Empty> : null}
      <Pages total={documentsData.total} page={page} onChange={setPage}/></>}</div>;
    const recordTab = <div className="wiki-tab-body"><Card size="small" className="wiki-filter-card knowledge-filter-card">
      <Segmented aria-label="知识检索执行状态" value={recordStatus} options={statuses} onChange={value => { setRecordStatus(value as KnowledgeRecordStatus); setRecordPage(1); }}/>
      <form className="wiki-filter-form knowledge-record-filter" onSubmit={searchRecords}>
        <label><span>Task 标识</span><Input value={taskInput} maxLength={128} allowClear onChange={event => setTaskInput(event.target.value)}/></label>
        <label><span>查询哈希前缀（至少 4 位）</span><Input value={hashInput} maxLength={64} pattern="[a-f0-9]{4,64}" allowClear onChange={event => setHashInput(event.target.value)}/></label>
        <label><span>执行日期（UTC+8）</span><Input type="date" value={dateInput} onChange={event => setDateInput(event.target.value)}/></label><Button htmlType="submit" icon={<FileSearchOutlined/>}>定位记录</Button>
      </form><p className="wiki-filter-note knowledge-filter-note">只保存 query_hash，不保存原始搜索词；哈希不保证无法反推。旧记录缺失身份、文档数和结果版本时显示“历史未记录”。展开时才读取结果明细。</p>
    </Card><ReadStatus {...records}/>{recordsData && <><Problems items={recordsData.problems}/>
      <p className="muted">日志状态：{label(recordsData.collection.status)} · {purposeLabel(scope.purpose)}。{scope.purpose !== 'unknown' && scope.purpose !== 'all' && '旧记录请切换至“未知用途 / 旧记录”。'}</p>
      {recordsData.items.length ? <ul className="wiki-record-list knowledge-record-list">{recordsData.items.map(row => <RecordItem key={row.key} row={row} scope={recordsQuery} revision={revision} open={open}/>)}</ul> : <Empty>{recordsData.collection.status === 'available' ? '已知采集范围内没有符合筛选的记录。' : '未取得符合筛选的记录；采集缺失不等于零使用。'}</Empty>}
      <Pages total={recordsData.total} page={recordPage} onChange={setRecordPage}/></>}</div>;
    return <section className="page wiki-page knowledge-page"><div className="page-heading wiki-page-heading"><div><h1 ref={heading} tabIndex={-1}><DatabaseOutlined/> 知识库</h1><p>长期知识与使用记录</p></div>
      <div className="wiki-page-controls"><Select className="wiki-project-select" aria-label="知识库项目范围" value={scope.project} onChange={project => changeScope({ project })} showSearch optionFilterProp="label"
        options={[{ value: '', label: '全部已注册项目' }, ...projects.map(project => ({ value: project.key, label: project.name }))]}/>
        <Segmented aria-label="知识统计时间范围" value={scope.days} options={[{ value: 7, label: '7 天' }, { value: 30, label: '30 天' }, { value: 90, label: '90 天' }]} onChange={value => changeScope({ days: value as KnowledgeDays })}/>
        <Select className="knowledge-purpose" aria-label="知识调用用途" value={scope.purpose} options={purposes} onChange={purpose => changeScope({ purpose })}/>
      </div></div><p className="knowledge-scope-note">全局页面范围由你明确选择；不会改变 AI 默认“当前项目 + 已注册共享”。记录数是已知证据，不是价值评分。</p>
      <Tabs activeKey={tab} onChange={value => setTab(value as Tab)} items={[
        { key: 'overview', label: <span><DatabaseOutlined/> 使用概况</span>, children: <Overview read={overview} open={open} chooseProject={project => changeScope({ project })} showRecords={showRecords} showAdopted={() => { setAdopted(true); setPage(1); setTab('documents'); }}/> },
        { key: 'documents', label: <span><ReadOutlined/> 知识条目</span>, children: documentTab },
        { key: 'records', label: <span><FileSearchOutlined/> 检索记录</span>, children: recordTab },
      ]}/><DocumentReader keys={keys} scope={scope} revision={revision} close={() => setKeys([])} back={() => setKeys(previous => previous.slice(0, -1))} open={open}
        restore={() => { if (entryFocus.current?.isConnected) entryFocus.current.focus(); else heading.current?.focus(); }}/>
    </section>;
}
