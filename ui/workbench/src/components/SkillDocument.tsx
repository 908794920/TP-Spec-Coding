import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Modal, Space, Spin, Tag, Typography } from 'antd';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';
import { api } from '../api';
import { useRead } from '../useRead';
import { SKILL_STATUS_LABELS, SOURCE_LABELS, type TopoNode } from '../graph/topology';
import { resolveSkillLink, type SkillDocumentLocation } from './skillDocumentLinks';

/** Both views open this reader by stable identity, never by display name or a Base-relative guess. */
export function SkillDocument({ node, onClose }: { node: TopoNode; onClose: () => void }) {
    const [history, setHistory] = useState<SkillDocumentLocation[]>([{ path: '', hash: '' }]);
    const [inspection, setInspection] = useState(false);
    const [revision, refresh] = useState(0);
    const [linkError, setLinkError] = useState('');
    const location = history.at(-1)!;
    const body = useRef<HTMLDivElement>(null), article = useRef<HTMLElement>(null);
    const waitingForInspection = node.status === 'disabled' && !inspection;
    const identity = waitingForInspection ? '' : JSON.stringify([node.id, location.path, inspection]);
    const read = useRead(identity, revision, signal => api.skillDocument(node.id, signal, location.path, inspection));
    // useRead preserves prior successes for other pages. A document must not present one as current
    // while reloading, after a failed read, or after the user has disabled/deleted its source.
    const current = !waitingForInspection && !read.loading && !read.error ? read.data : undefined;
    const mayInspect = !inspection && (waitingForInspection || read.error?.startsWith('SKILL_DISABLED'));
    const status = current?.status ?? node.status;
    const source = current?.source_kind ?? node.sourceKind;
    function follow(href: string) {
        if (!current) return;
        try {
            const target = resolveSkillLink(current.path, href);
            setLinkError('');
            setHistory(previous => [...previous, target]);
        } catch (error) { setLinkError(error instanceof Error ? error.message : '文档链接格式无效'); }
    }
    useEffect(() => {
        if (!current || !article.current || !body.current) return;
        body.current.scrollTop = 0;
        if (location.hash) {
            const target = [...article.current.querySelectorAll('[id]')].find(element => element.id === location.hash);
            if (target) body.current.scrollTop = target.getBoundingClientRect().top - body.current.getBoundingClientRect().top;
        }
    }, [current, location.hash]);
    const info = [
        ['能力 ID', node.id],
        ['启用标志（读取值）', (current?.enabled ?? node.enabled) === undefined ? '未记录' : (current?.enabled ?? node.enabled) ? '是' : '否'],
        ['来源目录', current?.source_root ?? node.sourceRoot],
        ['入口文件', current?.entry_path ?? node.path],
        ['当前文档', current?.path ?? (location.path || node.path)],
        ['声明上游', current?.upstream ?? node.upstream],
        ['声明版本', current?.version ?? node.version],
        ['当前文档 SHA-256', current?.content_sha256 ?? '尚无本次读取结果'],
        ['入口 SHA-256（目录读取）', current?.entry_sha256 ?? node.entrySha256],
    ];
    return <Modal title={`${current?.name ?? node.name} · 设定详情`} open onCancel={onClose} footer={null} width={900} style={{ top: 24 }}>
      <div className="skill-document" ref={body}>
        <Space className="skill-document-toolbar" wrap>
          <Button size="small" disabled={history.length < 2} onClick={() => { setLinkError(''); setHistory(previous => previous.slice(0, -1)); }}>返回上一篇</Button>
          <Button size="small" disabled={waitingForInspection} onClick={() => { setLinkError(''); refresh(value => value + 1); }}>重新读取正文</Button>
          <Tag>{SOURCE_LABELS[source] ?? source}</Tag>
          <Tag>{SKILL_STATUS_LABELS[status] ?? status}</Tag>
        </Space>
        <Typography.Paragraph type="secondary" className="skill-document-note">
          {current ? '以下来源信息来自本次正文读取；用途与关联仍为目录声明。' : '当前仅展示目录快照信息，不代表本次正文已读取成功。'}
          可读取不等于依赖齐备或执行已验证；文档指纹不代表整个来源包。
        </Typography.Paragraph>
        <dl className="skill-source-details">{info.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '未提供'}</dd></div>)}</dl>
        {node.sourceKind === 'external' && <div className="skill-source-description">
          <p><strong>用途（目录声明）：</strong>{node.description || '未提供；只能按精确 ID 指定，不猜测用途'}</p>
          <p><strong>关联（非执行记录）：</strong>{node.appliesTo.join('、') || '未关联'}</p>
        </div>}
        {!!node.reason && <Alert type="warning" showIcon title="目录来源说明" description={node.reason}/>}
        {mayInspect && <Alert type="warning" showIcon title="此能力已停用" description={<>
          正常执行读取仍被拒绝。此处仅供人工检查原始内容，不启用能力、不记录采用。
          <div><Button size="small" onClick={() => setInspection(true)}>只读查看停用内容</Button></div>
        </>}/>}
        {current?.status === 'disabled' && <Alert type="warning" showIcon title="停用内容 · 仅供人工只读检查" description="此次查看没有启用能力，也不构成执行或采用授权。"/>}
        {read.error && <Alert type="error" showIcon title="设定读取失败" description={read.error}/>}
        {linkError && <Alert type="warning" showIcon title="无法打开此链接" description={linkError}/>}
        {read.loading && <div role="status" className="skill-document-loading"><Spin description="正在读取设定…"/></div>}
        {current && <article ref={article} className="skill-markdown"><Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} skipHtml components={{
            a: ({ children, href }) => href && /^(https?:|mailto:)/i.test(href)
                ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                : href && !/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href)
                    ? <a href={href} onClick={event => { event.preventDefault(); follow(href); }}>{children}</a>
                    : <span title={href}>{children}</span>,
            img: ({ alt }) => <span>{alt ? `[图片：${alt}]` : '[图片]'}</span>,
        }}>{current.content.replace(/^---\r?\n(?:[\s\S]*?\r?\n)?---(?:\r?\n|$)/, '')}</Markdown></article>}
      </div>
    </Modal>;
}
