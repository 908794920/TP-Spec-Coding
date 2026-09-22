import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Alert, Button, Card, Checkbox, Collapse, Drawer, Input, Pagination, Segmented, Select, Space, Tabs, Tag } from 'antd';
import { ArrowLeftOutlined, BookOutlined, ClockCircleOutlined, FileSearchOutlined, LinkOutlined, ReadOutlined, SearchOutlined, UnorderedListOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import rehypeSlug from 'rehype-slug';
import remarkGfm from 'remark-gfm';
import { Empty, Problems, ReadStatus } from '../components/Facts';
import { timestampText, text } from '../facts';
import { useRead } from '../useRead';
import { wikiApi } from '../wikiApi';
import type { Envelope, Problem, ReadState } from '../types';
import type {
    WikiAttentionRow, WikiCollection, WikiDocumentData, WikiDocumentMetadata, WikiDays, WikiDocumentsData,
    WikiEnvelope, WikiOverviewData, WikiProjectOption, WikiProjectUsageRow, WikiRecord, WikiRecordResult,
    WikiRecordStatus, WikiRecordsData, WikiUsageRow,
} from '../wikiTypes';
import '../styles/wiki.css';

const PAGE_SIZE = 20;
const DAYS_OPTIONS = [{ label: '7 天', value: 7 }, { label: '30 天', value: 30 }, { label: '90 天', value: 90 }];
const STATUS_OPTIONS: { label: string; value: WikiRecordStatus }[] = [
    { label: '全部', value: 'all' },
    { label: '命中', value: 'hit' },
    { label: '零命中', value: 'zero' },
    { label: '失败', value: 'failed' },
];

type WikiRead<T> = ReadState<WikiEnvelope<T>>;
type WikiTab = 'overview' | 'documents' | 'records';

function valueOrDash(value: unknown): string {
    return value === null || value === undefined || value === '' ? '—' : String(value);
}

function numberOrDash(value: number | null | undefined): string {
    return value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN');
}

function ratioOrDash(value: number | null | undefined): string {
    return value === null || value === undefined || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(value * 100 % 1 ? 1 : 0)}%`;
}

function dateOrDash(value: string | null | undefined): string {
    return value ? timestampText(value) : '—';
}

function collectionLabel(value: WikiCollection | undefined): { label: string; color: string } {
    const status = String(value?.status || '').toLowerCase();
    if (status === 'available') return { label: '已采集', color: 'success' };
    if (status === 'partial') return { label: '部分采集', color: 'warning' };
    if (status === 'not_collected') return { label: '尚未采集', color: 'default' };
    if (status === 'unavailable') return { label: '读取失败', color: 'error' };
    return { label: value?.status ? `状态：${value.status}` : '状态未记录', color: 'default' };
}

function problemItems(items: Problem[] | undefined): Problem[] {
    return Array.isArray(items) ? items : [];
}

function WikiReadStatus<T>({ read }: { read: WikiRead<T> }) {
    /* Wiki envelopes deliberately keep context=null, which is a narrower version of the shared
       workbench envelope. Reusing the shared read presentation keeps stale/error wording identical
       across project and Wiki reads. */
    return <ReadStatus {...read as ReadState<Envelope<unknown>>}/>;
}

function ProjectSelector({ projects, value, onChange }: {
    projects: WikiProjectOption[];
    value: string;
    onChange: (value: string) => void;
}) {
    return <Select className="wiki-project-select" aria-label="Wiki 项目范围" value={value} onChange={onChange}
        options={[{ value: '', label: '全部项目' }, ...projects.map(project => ({ value: project.key, label: project.name || project.key }))]}
        optionFilterProp="label" showSearch allowClear={false}/>;
}

function DaysSelector({ value, onChange }: { value: WikiDays; onChange: (value: WikiDays) => void }) {
    return <Segmented className="wiki-days-select" aria-label="统计时间范围" options={DAYS_OPTIONS}
        value={value} onChange={next => onChange(Number(next) as WikiDays)}/>;
}

function WikiMetric({ label, value, detail, icon, onClick }: {
    label: string;
    value: string;
    detail: string;
    icon: ReactNode;
    onClick: () => void;
}) {
    return <button type="button" className="wiki-metric" onClick={onClick}>
      <span className="wiki-metric-icon" aria-hidden="true">{icon}</span>
      <span className="wiki-metric-copy"><span className="wiki-metric-label">{label}</span><strong>{value}</strong><small>{detail}</small></span>
    </button>;
}

function attentionLabel(kind: string): string {
    if (kind === 'zero') return '重复零命中';
    if (kind === 'stale') return '文档已陈旧';
    if (kind === 'unadopted') return '反复读取，未记录采用';
    return kind || '待关注';
}

function statusColor(value: string | null | undefined): string {
    const normalized = String(value || '').toLowerCase();
    if (['available', 'healthy', 'ok', 'hit', 'success', 'current', 'matched'].includes(normalized)) return 'success';
    if (['failed', 'error', 'stale', 'historical', 'missing', 'failed_index'].includes(normalized)) return 'error';
    if (['partial', 'warning', 'zero', 'unadopted', 'not_indexed', 'pending'].includes(normalized)) return 'warning';
    return 'default';
}

function statusText(value: string | null | undefined): string {
    const normalized = String(value || '').toLowerCase();
    const labels: Record<string, string> = {
        available: '可用', healthy: '健康', ok: '正常', partial: '部分可用', not_collected: '尚未采集',
        hit: '命中', zero: '零命中', failed: '失败', current: '当前版本', matched: '当前版本',
        historical: '历史版本', stale: '陈旧', missing: '缺失', unadopted: '反复读取，未记录采用',
        indexed: '已建立', index: '已建立', not_indexed: '未建立', pending: '建立中', failed_index: '建立失败',
    };
    return labels[normalized] || (value ? String(value) : '未记录');
}

function sourceLabel(document: WikiDocumentMetadata | undefined): string {
    if (!document) return '—';
    const parts = [document.project_name || document.project_key, document.repo_id, document.path].filter(Boolean);
    return parts.length ? parts.join(' / ') : '—';
}

function OverviewTab({ data, onMetric, onTrend, onProject, onDocument, onAttention }: {
    data?: WikiOverviewData;
    onMetric: (action: 'records' | 'hit-records' | 'documents' | 'adopted') => void;
    onTrend: (date: string) => void;
    onProject: (key: string) => void;
    onDocument: (key: string) => void;
    onAttention: (item: WikiAttentionRow) => void;
}) {
    const metrics = data?.metrics;
    const trend = data?.trend ?? [];
    const trendElement = useRef<HTMLDivElement>(null);
    useEffect(() => { if (trendElement.current) trendElement.current.scrollLeft = trendElement.current.scrollWidth; }, [data]);
    const hasActivity = trend.some(item => (item.searches ?? 0) > 0 || (item.adopted_tasks ?? 0) > 0);
    const maxActivity = Math.max(1, ...trend.flatMap(item => [item.searches ?? 0, item.hits ?? 0, item.adopted_tasks ?? 0]));
    const collection = collectionLabel(data?.collection);
    const maintenance = data?.maintenance;
    const adoption = data?.adoption_collection;
    const adoptionLabel = adoption?.status === 'available' ? { label: '已读取', color: 'success' }
        : adoption?.status === 'partial' ? { label: '部分可读', color: 'warning' }
        : adoption?.status === 'unavailable' ? { label: '读取失败', color: 'error' }
        : { label: '尚无可读取范围', color: 'default' };
    return <div className="wiki-overview">
      <div className="wiki-collection-note">
        <strong>检索日志</strong><Tag color={collection.color}>{collection.label}</Tag>
        <span>{data?.collection?.note || '统计数据来自已记录的 Wiki 读取与采用证据。'}</span>
        <span className="muted">保留 {numberOrDash(data?.collection?.retention_days)} 天 · 可访问项目 {numberOrDash(data?.collection?.accessible_projects)} / {numberOrDash(data?.collection?.total_projects)} · 采集开始 {dateOrDash(data?.collection?.started_at)}</span>
        {!!data?.collection?.missing_projects?.length && <span className="wiki-coverage-note">未完整采集：{data.collection.missing_projects.join('、')}</span>}
        {!!data?.collection?.unresolved_contexts && <span className="wiki-coverage-note">另有 {data.collection.unresolved_contexts} 个注册上下文无法解析，详见读取提示。</span>}
      </div>
      <div className="wiki-collection-note">
        <strong>采用记录</strong><Tag color={adoptionLabel.color}>{adoptionLabel.label}</Tag>
        <span>{adoption?.note || '正在读取任务采用记录…'}</span>
        {!!adoption?.missing_projects?.length && <span className="wiki-coverage-note">不可完整读取：{adoption.missing_projects.join('、')}</span>}
      </div>
      <div className="wiki-metrics-grid" aria-label="Wiki 使用指标">
        <WikiMetric label="AI 搜索次数" value={numberOrDash(metrics?.searches)} detail="打开全部检索记录" icon={<SearchOutlined/>} onClick={() => onMetric('records')}/>
        <WikiMetric label="命中率" value={ratioOrDash(metrics?.hit_rate)} detail="查看命中记录" icon={<FileSearchOutlined/>} onClick={() => onMetric('hit-records')}/>
        <WikiMetric label="已记录采用任务数" value={numberOrDash(metrics?.adopted_tasks)} detail="浏览采用文档" icon={<BookOutlined/>} onClick={() => onMetric('adopted')}/>
        <WikiMetric label="已记录采用文档数" value={numberOrDash(metrics?.adopted_documents)} detail="浏览采用文档" icon={<ReadOutlined/>} onClick={() => onMetric('adopted')}/>
      </div>
      <Card size="small" className="wiki-section-card" title="当前筛选范围内最近已记录活动">
        <div className="wiki-recent-activity">{(['search', 'read', 'adopted'] as const).map(kind => {
            const item = data?.recent_activity?.[kind];
            const empty = item?.status === 'unavailable' ? '读取失败，无法判断'
                : item?.status === 'not_collected' ? '尚未采集'
                : item?.status === 'partial' ? '已知范围内未记录'
                : item ? '当前范围未记录' : '正在读取…';
            return <div key={kind}><span>{({ search: '最近搜索', read: '最近正文读取', adopted: '最近采用' })[kind]}</span>
              <strong>{item?.at ? dateOrDash(item.at) : empty}</strong>
              {item?.status === 'partial' && <small>已知范围内最近记录，缺失范围见上方说明</small>}
            </div>;
        })}</div>
      </Card>
      <Card size="small" className="wiki-section-card" title={<span><ClockCircleOutlined/> 每日趋势</span>} extra={<span className="muted">点击日期查看该日记录</span>}>
        {hasActivity ? <>
          <div className="wiki-trend-legend"><span>搜索</span><span>命中</span><span>采用任务</span></div>
          <div ref={trendElement} className="wiki-trend" aria-label="每日使用趋势">{trend.map(item => {
            const label = `${item.date} · 搜索 ${numberOrDash(item.searches)} · 命中 ${numberOrDash(item.hits)} · 采用 ${numberOrDash(item.adopted_tasks)}`;
            return <button type="button" className="wiki-trend-item" key={item.date} onClick={() => onTrend(item.date)} title={label} aria-label={label}>
              <span className="wiki-trend-bar-wrap">{[item.searches, item.hits, item.adopted_tasks].map((value, index) => <span key={index} className={`wiki-trend-bar series-${index}`} style={{ height: `${(value ?? 0) / maxActivity * 80}px` }}/>)}</span>
              <small>{item.date.slice(5)}</small>
            </button>;
          })}</div>
        </> : <Empty title={data?.collection?.status === 'not_collected' ? '尚未开始采集检索使用' : '当前范围暂无使用趋势'}>后续真实搜索与已记录采用会显示在这里；历史未记录不代表未使用。</Empty>}

      </Card>
      <Card size="small" className="wiki-section-card" title="项目使用">
        {(data?.project_usage ?? []).length ? <ul className="wiki-usage-list">{(data?.project_usage ?? []).map((row: WikiProjectUsageRow) => <li key={row.key}>
          <button type="button" onClick={() => onProject(row.key)}><span className="wiki-usage-name">{row.name || row.key}</span><span>搜索 {numberOrDash(row.searches)}</span><span>命中率 {ratioOrDash(row.hit_rate)}</span><span>阅读 {numberOrDash(row.reads)}</span><span>采用 {numberOrDash(row.adopted_tasks)}</span><time>{dateOrDash(row.last_used)}</time></button>
        </li>)}</ul> : <Empty title="暂无项目使用记录">项目使用数据尚未采集或当前范围没有记录。</Empty>}
      </Card>
      <div className="wiki-two-columns">
        <Card size="small" className="wiki-section-card" title="需要关注">
          {(data?.attention ?? []).length ? <ul className="wiki-attention-list">{(data?.attention ?? []).map((item: WikiAttentionRow, index) => <li key={`${item.kind}:${item.title}:${index}`}>
            <button type="button" onClick={() => onAttention(item)}><Tag color={statusColor(item.kind)}>{attentionLabel(item.kind)}</Tag><span>{item.title}</span><strong>{numberOrDash(item.count)}</strong></button>
          </li>)}</ul> : <Empty title="暂无关注项">当前没有已记录的重复零命中、过期或反复读取但未记录采用的情况。</Empty>}
        </Card>
        <Card size="small" className="wiki-section-card" title="热门文档">
          {(data?.popular ?? []).length ? <ul className="wiki-popular-list">{(data?.popular ?? []).map(document => <li key={document.key}><button type="button" onClick={() => onDocument(document.key)}><span>{document.title || document.path || document.key}</span><small>{sourceLabel(document)}</small><em>阅读 {numberOrDash(document.reads)} · 采用 {numberOrDash(document.adopted_tasks)} · {dateOrDash(document.last_used)}</em></button></li>)}</ul> : <Empty title="暂无热门文档">当前时间范围内没有文档阅读记录。</Empty>}
        </Card>
      </div>
      <Card size="small" className="wiki-section-card" title="维护概况">
        <div className="wiki-maintenance-summary"><span><small>文档</small><strong>{numberOrDash(maintenance?.document_count)}</strong></span><span><small>仓库</small><strong>{numberOrDash(maintenance?.repo_count)}</strong></span><span><small>最近更新</small><strong>{dateOrDash(maintenance?.updated_at)}</strong></span></div>
        {(maintenance?.repositories ?? []).length || (data?.indexes ?? []).length ? <Collapse className="wiki-maintenance-repositories" size="small" items={[{ key: 'details', label: `查看仓库维护明细 · ${(maintenance?.repositories ?? []).length || 0} 个仓库`, children: <div className="wiki-maintenance-details">
            {(maintenance?.repositories ?? []).length ? <Collapse ghost size="small" items={(maintenance?.repositories ?? []).map((repo, index) => ({
                key: `${repo.repo_id || repo.project_key || 'repo'}:${index}`,
                label: <span className="wiki-repo-label"><span>{repo.project_name || repo.project_key || '项目未记录'} · {repo.repo_id || '仓库未记录'}</span><Tag color={statusColor(repo.status)}>{statusText(repo.status)}</Tag><small>{numberOrDash(repo.document_count)} 篇</small></span>,
                children: <div className="wiki-repo-detail"><p>更新时间：{dateOrDash(repo.updated_at)}</p>{repo.report && Object.keys(repo.report).length ? <pre>{JSON.stringify(repo.report, null, 2)}</pre> : <p className="muted">维护报告未记录。</p>}</div>,
            }))}/> : <p className="muted">仓库维护明细未记录。</p>}
            {!!(data?.indexes ?? []).length && <div className="wiki-maintenance-indexes"><h4>索引状态</h4><ul className="wiki-index-list">{(data?.indexes ?? []).map((item, index) => <li key={`${item.source_id || 'source'}:${index}`}><code>{item.source_id || '来源未记录'}</code><Tag color={statusColor(item.status)}>{statusText(item.status)}</Tag><time>{dateOrDash(item.indexed_at)}</time>{['missing', 'not_indexed', 'pending', 'failed_index'].includes(String(item.status || '').toLowerCase()) && <small>需要通过 CLI 维护建立索引</small>}</li>)}</ul></div>}
        </div> }]}/> : <p className="muted">仓库维护明细与索引状态未记录。</p>}
      </Card>
      {!!(data?.problems ?? []).length && <Problems items={problemItems(data?.problems)}/>}
    </div>;
}

function DocumentRow({ document, onOpen }: { document: WikiDocumentMetadata; onOpen: (key: string) => void }) {
    return <li className="wiki-document-row"><button type="button" onClick={() => onOpen(document.key)}>
      <span className="wiki-document-title"><strong>{document.title || document.path || document.key}</strong><small>{document.path || '来源路径未记录'}</small>{document.snippet && <small className="wiki-document-snippet">{document.snippet}</small>}</span>
      <span className="wiki-document-project">{document.project_name || document.project_key || '项目未记录'}<small>{document.repo_id || '仓库未记录'}</small></span>
      <span><Tag color={statusColor(document.type)}>{valueOrDash(document.type)}</Tag><Tag color={statusColor(document.status)}>{statusText(document.status)}</Tag></span>
      <span className="wiki-document-numbers">阅读 {numberOrDash(document.reads)}<br/>采用 {numberOrDash(document.adopted_tasks)}</span>
      <time>{dateOrDash(document.updated_at)}</time>
    </button></li>;
}

function DocumentsTab({ project, days, revision, adoptedOnly, onAdoptedChange, onOpenDocument }: {
    project: string;
    days: WikiDays;
    revision: number;
    adoptedOnly: boolean;
    onAdoptedChange: (value: boolean) => void;
    onOpenDocument: (key: string) => void;
}) {
    const [repoDraft, setRepoDraft] = useState('');
    const [kindDraft, setKindDraft] = useState('');
    const [queryDraft, setQueryDraft] = useState('');
    const [filters, setFilters] = useState({ repo: '', kind: '', q: '' });
    const [page, setPage] = useState(1);
    useEffect(() => { setPage(1); setRepoDraft(''); setKindDraft(''); setQueryDraft(''); setFilters({ repo: '', kind: '', q: '' }); }, [project, days]);
    const request = JSON.stringify(['wiki-documents', project, days, filters.repo, filters.kind, filters.q, adoptedOnly, page]);
    const read = useRead<WikiEnvelope<WikiDocumentsData>>(request, revision, signal => wikiApi.documents({ project, days, repo: filters.repo, kind: filters.kind, q: filters.q, page, adopted: adoptedOnly }, signal));
    const data = read.data?.data;
    const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setPage(1); setFilters({ repo: repoDraft, kind: kindDraft, q: queryDraft.trim() }); };
    const pageSize = data?.page_size || PAGE_SIZE;
    return <section className="wiki-tab-panel">
      <Card size="small" className="wiki-filter-card">
        <form className="wiki-filter-form" onSubmit={submit}>
          <label>仓库<Select value={repoDraft || undefined} placeholder="全部仓库" allowClear onChange={value => setRepoDraft(value || '')} options={(data?.repositories ?? []).map(repo => ({ value: repo.id, label: repo.name || repo.id }))}/></label>
          <label>文档类型<Select value={kindDraft || undefined} placeholder="全部类型" allowClear onChange={value => setKindDraft(value || '')} options={(data?.types ?? []).map(kind => ({ value: kind, label: kind }))}/></label>
          <label className="wiki-query-field">关键词<Input value={queryDraft} allowClear placeholder="标题、路径或内容" onChange={event => setQueryDraft(event.target.value)}/></label>
          <Button type="primary" htmlType="submit" icon={<SearchOutlined/>}>检索</Button>
          <Checkbox checked={adoptedOnly} onChange={event => { onAdoptedChange(event.target.checked); setPage(1); }}>仅显示已采用文档</Checkbox>
        </form>
        <p className="muted wiki-filter-note">检索只读取已登记的文档，不会写入检索记录或手动增加统计。</p>
      </Card>
      <WikiReadStatus read={read}/>
      {data && <><Problems items={problemItems(data.problems)}/>
        {(data.items ?? []).length ? <><ul className="wiki-document-list" aria-label="Wiki 文档列表">{(data.items ?? []).map(document => <DocumentRow key={document.key} document={document} onOpen={onOpenDocument}/>)}</ul><div className="wiki-pagination"><span className="muted">共 {numberOrDash(data.total)} 篇</span><Pagination current={data.page || page} pageSize={pageSize} total={data.total || 0} showSizeChanger={false} onChange={next => setPage(next)}/></div></> : <Empty title="没有符合条件的文档">调整项目、仓库、类型或关键词后重新检索。</Empty>}
      </>}
    </section>;
}

function versionPresentation(result: WikiRecordResult): { label: string; color: string } {
    const normalized = String(result.version_status || '').toLowerCase();
    if (normalized === 'missing') return { label: '当前文档不可用', color: 'default' };
    if (!result.content_hash || !result.current_hash) return { label: '版本未确认', color: 'default' };
    return result.content_hash === result.current_hash
        ? { label: '当前版本', color: 'success' }
        : { label: '历史版本', color: 'warning' };
}

function RecordResult({ result, onOpenDocument }: { result: WikiRecordResult; onOpenDocument: (key: string) => void }) {
    const version = versionPresentation(result);
    const contentHash = result.content_hash ? result.content_hash.slice(0, 12) : '—';
    const currentHash = result.current_hash ? result.current_hash.slice(0, 12) : '—';
    return <li className="wiki-record-result"><span className="wiki-record-result-title">{result.key ? <button type="button" onClick={() => onOpenDocument(result.key!)}>{result.title || result.key}</button> : <strong>{result.title || result.id || '结果未记录'}</strong>}</span><Tag color={version.color}>{version.label}</Tag><small>记录 {contentHash} · 当前 {currentHash}</small></li>;
}

function RecordRow({ record, onOpenDocument }: { record: WikiRecord; onOpenDocument: (key: string) => void }) {
    const results = record.results ?? [];
    const displayStatus = record.status === 'completed' ? (record.result_count ? 'hit' : 'zero') : record.status;
    return <li className="wiki-record-row"><details>
      <summary><span className="wiki-record-status"><Tag color={statusColor(displayStatus)}>{statusText(displayStatus)}</Tag><strong>{record.query || '查询内容未记录'}</strong></span><span>{record.project_name || record.project_key || '项目未记录'}</span><span>结果 {numberOrDash(record.result_count)} · {numberOrDash(record.elapsed_ms)} ms</span><time>{dateOrDash(record.created_at)}</time></summary>
      <div className="wiki-record-detail"><div className="wiki-record-meta"><span>操作：{valueOrDash(record.operation)}</span><span>Task：{record.task_id || '未关联'}</span><span>角色：{record.actor_role || '未关联'}</span><span>回执：{valueOrDash(record.receipt_id)}</span></div>{record.error && <Alert type="error" showIcon title={record.error}/>}<div className="wiki-record-results"><strong>结果详情</strong>{results.length ? <ul>{results.map((result, index) => <RecordResult key={`${result.id || result.key || 'result'}:${index}`} result={result} onOpenDocument={onOpenDocument}/>)}</ul> : <span className="muted">没有返回文档结果。</span>}</div></div>
    </details></li>;
}

function RecordsTab({ project, days, revision, initialStatus, initialDate, initialQuery, onOpenDocument }: {
    project: string;
    days: WikiDays;
    revision: number;
    initialStatus: WikiRecordStatus;
    initialDate: string;
    initialQuery: string;
    onOpenDocument: (key: string) => void;
}) {
    const [statusDraft, setStatusDraft] = useState<WikiRecordStatus>(initialStatus);
    const [dateDraft, setDateDraft] = useState(initialDate);
    const [queryDraft, setQueryDraft] = useState(initialQuery);
    const [filters, setFilters] = useState({ status: initialStatus, date: initialDate, q: initialQuery });
    const [page, setPage] = useState(1);
    useEffect(() => { setPage(1); setStatusDraft(initialStatus); setDateDraft(initialDate); setQueryDraft(initialQuery); setFilters({ status: initialStatus, date: initialDate, q: initialQuery }); }, [project, days, initialStatus, initialDate, initialQuery]);
    const request = JSON.stringify(['wiki-records', project, days, filters.status, filters.date, filters.q, page]);
    const read = useRead<WikiEnvelope<WikiRecordsData>>(request, revision, signal => wikiApi.records({ project, days, status: filters.status, date: filters.date, q: filters.q, page }, signal));
    const data = read.data?.data;
    const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setPage(1); setFilters({ status: statusDraft, date: dateDraft, q: queryDraft.trim() }); };
    const pageSize = data?.page_size || PAGE_SIZE;
    const collection = collectionLabel(data?.collection);
    return <section className="wiki-tab-panel">
      <Card size="small" className="wiki-filter-card">
        <form className="wiki-filter-form" onSubmit={submit}>
          <label>状态<Select value={statusDraft} onChange={value => setStatusDraft(value as WikiRecordStatus)} options={STATUS_OPTIONS}/></label>
          <label>日期<Input type="date" value={dateDraft} onChange={event => setDateDraft(event.target.value)}/></label>
          <label className="wiki-query-field">查询关键词<Input value={queryDraft} allowClear placeholder="查询文本或项目" onChange={event => setQueryDraft(event.target.value)}/></label>
          <Button type="primary" htmlType="submit" icon={<SearchOutlined/>}>筛选</Button>
        </form>
        <p className="muted wiki-filter-note">记录状态：<Tag color={collection.color}>{collection.label}</Tag> {data?.collection?.note || '历史检索记录只读展示。'}</p>
      </Card>
      <WikiReadStatus read={read}/>
      {data && <><Problems items={problemItems(data.problems)}/>{(data.items ?? []).length ? <><ul className="wiki-record-list" aria-label="Wiki 检索记录">{(data.items ?? []).map((item, index) => <RecordRow key={`${item.key}:${index}`} record={item} onOpenDocument={onOpenDocument}/>)}</ul><div className="wiki-pagination"><span className="muted">共 {numberOrDash(data.total)} 条</span><Pagination current={data.page || page} pageSize={pageSize} total={data.total || 0} showSizeChanger={false} onChange={next => setPage(next)}/></div></> : <Empty title="没有符合条件的检索记录">调整状态、日期或关键词后重新筛选。</Empty>}</>}
    </section>;
}

function wikiMarkdown(raw: string): string {
    let fence = '';
    return raw.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '').split(/\r?\n/).map(line => {
        const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1];
        if (marker) { if (!fence) fence = marker; else if (marker[0] === fence[0] && marker.length >= fence.length) fence = ''; return line; }
        if (fence) return line;
        return line.replace(/<cite\b[^>]*\/?\s*>/gi, tag => {
            const path = /\bpath=["']([^"']+)["']/i.exec(tag)?.[1];
            const range = /\bline=["']([^"']+)["']/i.exec(tag)?.[1];
            return path ? '`源码：' + path.replace(/`/g, '') + (range ? ':' + range.replace(/`/g, '') : '') + '`' : '';
        });
    }).join('\n');
}

function UsageList({ usage }: { usage: WikiUsageRow[] }) {
    return usage.length ? <ul className="wiki-document-usage">{usage.map((item, index) => <li key={`${item.receipt_id || item.task_id || 'usage'}:${index}`}><span><strong>{valueOrDash(item.task_id)}</strong><small>{valueOrDash(item.actor_role)} · {valueOrDash(item.stage)}</small></span><time>{dateOrDash(item.created_at)}</time>{item.receipt_id && <code>{item.receipt_id}</code>}{item.evidence?.length ? <small>{item.evidence.join(' · ')}</small> : null}</li>)}</ul> : <p className="muted">尚无相关采用或阅读证据。</p>;
}

function DocumentDrawer({ documentKey, days, revision, canGoBack, onBack, onClose, onOpenDocument }: {
    documentKey: string;
    days: WikiDays;
    revision: number;
    canGoBack: boolean;
    onBack: () => void;
    onClose: () => void;
    onOpenDocument: (key: string) => void;
}) {
    const read = useRead<WikiEnvelope<WikiDocumentData>>(documentKey ? JSON.stringify(['wiki-document', documentKey, days]) : '', revision, signal => wikiApi.document(documentKey, days, signal));
    const data = read.data?.data;
    const document = data?.document;
    const content = useMemo(() => wikiMarkdown(data?.content || ''), [data?.content]);
    const article = useRef<HTMLElement>(null);
    const [headings, setHeadings] = useState<{ level: number; title: string; id: string }[]>([]);
    useEffect(() => {
        setHeadings(Array.from(article.current?.querySelectorAll('h1,h2,h3') ?? []).map(heading => ({
            level: Number(heading.tagName.slice(1)), title: heading.textContent || '', id: heading.id,
        })));
    }, [content]);
    const links = data?.links ?? [];
    const linkByHref = useMemo(() => new Map(links.map(link => [link.href, link])), [links]);
    return <Drawer className="wiki-document-drawer" open={!!documentKey} onClose={onClose} size={720} title={<span>{document?.title || document?.path || 'Wiki 文档'}</span>} extra={<Button type="text" icon={<ArrowLeftOutlined/>} disabled={!canGoBack} onClick={onBack}>返回</Button>}>
      <WikiReadStatus read={read}/>
      {data && <><Problems items={problemItems(data.problems)}/><div className="wiki-document-heading"><div><span className="eyebrow">Wiki 文档</span><h2>{document?.title || document?.path || documentKey}</h2><p className="path">{sourceLabel(document)}</p></div><Space wrap><Tag color={statusColor(document?.status)}>{statusText(document?.status)}</Tag><Tag>{valueOrDash(document?.type)}</Tag></Space></div>
        <div className="wiki-document-layout">
          <aside className="wiki-toc" aria-label="文档目录"><strong><UnorderedListOutlined/> 目录</strong>{headings.length ? <ol>{headings.map(heading => <li key={heading.id} className={`wiki-toc-level-${heading.level}`}><a href={`#${heading.id}`}>{heading.title}</a></li>)}</ol> : <span className="muted">没有标题</span>}<div className="wiki-source-box"><strong>来源</strong><span>{document?.path || '路径未记录'}</span><span>更新：{dateOrDash(document?.updated_at)}</span><code>{document?.content_hash || '哈希未记录'}</code></div></aside>
          <article ref={article} className="wiki-markdown"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={{
              a: ({ href, children }) => {
                  const local = href ? linkByHref.get(href) : undefined;
                  if (local) return <a href={local.href} onClick={event => { event.preventDefault(); onOpenDocument(local.key); }} title={`打开 ${local.title}`}>{children}</a>;
                  if (href && /^(https?:|mailto:)/i.test(href)) return <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>;
                  if (href?.startsWith('#')) return <a href={href}>{children}</a>;
                  return <span className="wiki-unregistered-link" title="未登记的内部链接，已禁用">{children}</span>;
              },
              img: ({ alt }) => <span className="wiki-image-placeholder" role="img" aria-label={alt || '图片'}>图片：{alt || '未提供替代文字'}（图片未自动加载）</span>,
          }}>{content || '文档正文未记录。'}</ReactMarkdown></article>
        </div>
        <section className="wiki-document-usage-section"><h3>相关使用</h3><UsageList usage={data.usage ?? []}/></section>
        <section className="wiki-document-links"><h3><LinkOutlined/> 已登记的内部链接</h3>{links.length ? <ul>{links.map(link => <li key={`${link.href}:${link.key}`}><button type="button" onClick={() => onOpenDocument(link.key)}>{link.title || link.key}</button><code>{link.href}</code></li>)}</ul> : <p className="muted">没有已登记的内部链接。</p>}</section>
      </>}
    </Drawer>;
}

export function WikiPage({ revision }: { revision: number }) {
    const [tab, setTab] = useState<WikiTab>('overview');
    const [days, setDays] = useState<WikiDays>(30);
    const [project, setProject] = useState('');
    const [documentKey, setDocumentKey] = useState('');
    const [documentHistory, setDocumentHistory] = useState<string[]>([]);
    const [adoptedOnly, setAdoptedOnly] = useState(false);
    const [recordsIntent, setRecordsIntent] = useState<{ status: WikiRecordStatus; date: string; query: string; nonce: number }>({ status: 'all', date: '', query: '', nonce: 0 });
    const [projectOptions, setProjectOptions] = useState<WikiProjectOption[]>([]);
    const overviewRead = useRead<WikiEnvelope<WikiOverviewData>>(JSON.stringify(['wiki-overview', project, days]), revision, signal => wikiApi.overview(project, days, signal));
    const overview = overviewRead.data?.data;
    useEffect(() => { if (overview?.projects) setProjectOptions(overview.projects); }, [overview?.projects]);
    const projects = overview?.projects ?? projectOptions;
    function openDocument(key: string) {
        if (!key) return;
        if (documentKey && documentKey !== key) setDocumentHistory(history => [...history, documentKey]);
        setDocumentKey(key);
    }
    function closeDocument() { setDocumentKey(''); setDocumentHistory([]); }
    function backDocument() {
        const previous = documentHistory[documentHistory.length - 1];
        if (previous) { setDocumentKey(previous); setDocumentHistory(history => history.slice(0, -1)); }
        else closeDocument();
    }
    function openMetric(action: 'records' | 'hit-records' | 'documents' | 'adopted') {
        if (action === 'adopted') { setAdoptedOnly(true); setTab('documents'); return; }
        setTab(action === 'records' || action === 'hit-records' ? 'records' : 'documents');
        if (action === 'records' || action === 'hit-records') setRecordsIntent(intent => ({ status: action === 'hit-records' ? 'hit' : 'all', date: '', query: '', nonce: intent.nonce + 1 }));
    }
    function openTrend(date: string) { setRecordsIntent(intent => ({ status: 'all', date, query: '', nonce: intent.nonce + 1 })); setTab('records'); }
    function openAttention(item: WikiAttentionRow) {
        if (item.document_key) { openDocument(item.document_key); return; }
        setProject(item.project_key || '');
        setRecordsIntent(intent => ({ status: item.kind === 'zero' ? 'zero' : 'all', date: '', query: item.query || '', nonce: intent.nonce + 1 }));
        setTab('records');
    }
    function openProject(key: string) { setProject(key); setTab('overview'); }
    const tabItems = [{ key: 'overview', label: '使用概况' }, { key: 'documents', label: '文档' }, { key: 'records', label: '检索记录' }];
    return <div className="page wiki-page"><div className="page-heading wiki-page-heading"><div><span className="eyebrow">Wiki</span><h2>文档与检索使用</h2><p>查看已登记 Wiki 文档、历史检索与任务采用证据。所有数据为只读读取。</p></div><div className="wiki-page-controls"><ProjectSelector projects={projects} value={project} onChange={value => { setProject(value); setTab('overview'); }}/><DaysSelector value={days} onChange={value => setDays(value)}/></div></div>
       <WikiReadStatus read={overviewRead}/><Tabs className="wiki-tabs" activeKey={tab} onChange={key => setTab(key as WikiTab)} items={tabItems}/>
      {tab === 'overview' && <OverviewTab data={overview} onMetric={openMetric} onTrend={openTrend} onProject={openProject} onDocument={openDocument} onAttention={openAttention}/>}
      {tab === 'documents' && <DocumentsTab key={`documents:${project}:${days}:${adoptedOnly}`} project={project} days={days} revision={revision} adoptedOnly={adoptedOnly} onAdoptedChange={setAdoptedOnly} onOpenDocument={openDocument}/>}
      {tab === 'records' && <RecordsTab key={`records:${recordsIntent.nonce}:${project}:${days}`} project={project} days={days} revision={revision} initialStatus={recordsIntent.status} initialDate={recordsIntent.date} initialQuery={recordsIntent.query} onOpenDocument={openDocument}/>}
      <DocumentDrawer documentKey={documentKey} days={days} revision={revision} canGoBack={documentHistory.length > 0} onBack={backDocument} onClose={closeDocument} onOpenDocument={openDocument}/>
    </div>;
}
