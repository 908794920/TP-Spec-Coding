import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Alert, Button, Input, Tag } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { api } from '../api';
import { filterTasks, stateLabel, stateTone } from '../facts';
import type { Context, TaskIndexRow } from '../types';

/* Tone names follow the existing CSS contract: only Runtime-recorded states get a colour, so the
   list never implies a state the Runtime did not record. */
const toneColor: Record<string, string | undefined> = { blocked: 'error', completed: 'success', active: 'processing', unknown: 'warning' };
/* A hit keeps the project it came from: the same task_id can exist in more than one project, and
   opening a hit has to select the right context instead of reusing whatever was selected before. */
type Hit = TaskIndexRow & { context_key: string; project_name: string };
/* Long result lists are cut off with the remainder still counted, so the count is never wrong. */
const MAX_HITS = 20;

/* Reads every registered project's index, in parallel, only while the panel is open: a closed panel
   costs no request. The effect is keyed on the project *set* (a primitive) and reads the array from
   a ref, because keying on an array identity would re-run the read on every render. */
function useAllTasks(contexts: Context[], revision: number, enabled: boolean) {
    const latest = useRef(contexts);
    latest.current = contexts;
    const scope = contexts.map(context => context.context_key).join('\n');
    const [rows, setRows] = useState<Hit[]>([]), [loading, setLoading] = useState(false), [error, setError] = useState('');
    useEffect(() => {
        setLoading(false);
        setRows([]);
        setError('');
        if (!enabled || !scope)
            return;
        const controller = new AbortController();
        setLoading(true);
        Promise.all(latest.current.map(async context => {
            const result = await api.project(context.context_key, controller.signal);
            const name = context.name || context.project_id;
            return (result.data.task_index ?? []).map(row => ({ ...row, context_key: context.context_key, project_name: name }));
        })).then(groups => {
            if (controller.signal.aborted)
                return;
            setRows(groups.flat());
            setLoading(false);
        }).catch((reason: unknown) => {
            /* A failed project is reported rather than skipped: a shortened list would read as
               "no such task" when the truth is "that project was not read". */
            if (controller.signal.aborted)
                return;
            setRows([]);
            setLoading(false);
            setError(reason instanceof Error ? reason.message : String(reason));
        });
        return () => controller.abort();
    }, [enabled, scope, revision]);
    return { rows, loading, error };
}

export function TaskSearch({ contexts, revision, onOpenTask }: {
    contexts: Context[];
    revision: number;
    onOpenTask: (contextKey: string, taskId: string) => void;
}) {
    const [open, setOpen] = useState(false), [query, setQuery] = useState('');
    const [activeIndex, setActiveIndex] = useState(0);
    const box = useRef<HTMLDivElement>(null);
    const trigger = useRef<HTMLButtonElement | HTMLAnchorElement>(null);
    const panelId = useId(), listId = `${panelId}-hits`;
    const { rows, loading, error } = useAllTasks(contexts, revision, open);
    /* The query is the only filter. A task search that silently hid retired or completed work would
       answer a narrower question than the one that was asked. */
    const hits = useMemo(() => (!loading && query.trim() ? filterTasks(rows, query, '') : []), [loading, rows, query]);
    const shown = hits.slice(0, MAX_HITS);
    // Reset on a change in result identities or order, not on the new array from slice().
    const shownKey = JSON.stringify(shown.map(hit => [hit.context_key, hit.task_id]));
    const activeHit = shown[activeIndex];
    const activeId = activeHit ? `${listId}-${activeIndex}` : undefined;
    useLayoutEffect(() => setActiveIndex(0), [query, shownKey]);
    useEffect(() => {
        if (activeId) document.getElementById(activeId)?.scrollIntoView({ block: 'nearest' });
    }, [activeId, query, shownKey]);

    function close(returnFocus = true) {
        setOpen(false);
        setQuery('');
        if (returnFocus) requestAnimationFrame(() => trigger.current?.focus());
    }
    function openHit(hit: Hit) {
        onOpenTask(hit.context_key, hit.task_id);
        close(false);
        requestAnimationFrame(() => document.getElementById('main-content')?.focus());
    }
    function handlePanelKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
        if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229)
            return;
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            close();
            return;
        }
        if (!(event.target instanceof HTMLInputElement) || !activeHit)
            return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const offset = event.key === 'ArrowDown' ? 1 : -1;
            setActiveIndex(index => Math.max(0, Math.min(shown.length - 1, index + offset)));
        } else if (event.key === 'Enter') {
            event.preventDefault();
            openHit(activeHit);
        }
    }
    useEffect(() => {
        const onShortcut = (event: KeyboardEvent) => {
            if (event.defaultPrevented || event.isComposing || event.keyCode === 229 ||
                !(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase() !== 'k')
                return;
            const focused = document.activeElement;
            if (focused instanceof HTMLElement && (focused.matches('input, textarea, select') || focused.isContentEditable))
                return;
            if (document.querySelector('dialog:modal'))
                return;
            const overlays = document.querySelectorAll('.ant-modal-wrap, .ant-drawer-open .ant-drawer-section');
            if (Array.from(overlays).some(element => {
                const { width, height } = element.getBoundingClientRect();
                const { visibility, opacity, pointerEvents } = getComputedStyle(element);
                return width > 0 && height > 0 && visibility === 'visible' && opacity !== '0' && pointerEvents !== 'none';
            })) return;
            event.preventDefault();
            setOpen(true);
            box.current?.querySelector('input')?.focus();
        };
        window.addEventListener('keydown', onShortcut);
        return () => window.removeEventListener('keydown', onShortcut);
    }, []);
    /* The panel is our own markup rather than a popover component, so dismissal is explicit here:
       a pointer press anywhere outside it closes it, as does Escape. */
    useEffect(() => {
        if (!open)
            return;
        const onPointerDown = (event: PointerEvent) => {
            if (!box.current?.contains(event.target as Node)) {
                setOpen(false);
                setQuery('');
            }
        };
        document.addEventListener('pointerdown', onPointerDown);
        return () => document.removeEventListener('pointerdown', onPointerDown);
    }, [open]);
    return <div className="task-search" ref={box}>
      <Button ref={trigger} type="text" className="task-search-toggle" icon={<SearchOutlined/>} aria-expanded={open} aria-controls={panelId}
        aria-label={open ? '收起任务查询' : '按 TASK ID 或标题查询任务'} title="查询任务（TASK ID / 标题）"
        onClick={() => (open ? close() : setOpen(true))}/>
      {open && <div className="task-search-panel" id={panelId} onKeyDown={handlePanelKeyDown}>
        <Input className="task-search-input" autoFocus allowClear value={query} prefix={<SearchOutlined/>}
          aria-label="按 TASK ID 或标题查询任务" placeholder="按 TASK ID 或标题查询"
          role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={shown.length ? listId : undefined}
          aria-activedescendant={activeId}
          onChange={event => setQuery(event.target.value)}/>
        {loading && <p className="muted" role="status">正在读取 {contexts.length} 个项目的任务索引…</p>}
        {!!error && <Alert type="error" showIcon title={`查询未完成：${error}`}/>}
        {!loading && !error && !query.trim() && <p className="muted">已读到 {rows.length} 个任务，输入 TASK ID 或标题开始查询。</p>}
        {!loading && !error && !!query.trim() && !hits.length && <p className="muted">没有匹配「{query.trim()}」的任务。</p>}
        {!!shown.length && <ul className="task-search-hits" id={listId} role="listbox" aria-label="查询结果">{shown.map((hit, index) => <li role="presentation" key={`${hit.context_key}\u0000${hit.task_id}`}>
          <button type="button" className="task-hit" id={`${listId}-${index}`} role="option" aria-selected={index === activeIndex}
            style={index === activeIndex
                ? { backgroundColor: 'var(--accent-soft)' } : undefined}
            title={`${hit.task_id} · ${hit.title || '未记录标题'} · ${hit.project_name}`} onClick={() => openHit(hit)}>
            <span className="hit-head"><span className="hit-id">{hit.task_id}</span>
              <Tag variant="filled" color={toneColor[stateTone('task', hit.state)]}>{stateLabel('task', hit.state)}</Tag>
              <span className="hit-project">{hit.project_name}</span></span>
            <span className="hit-title">{hit.title || '未记录标题'}</span>
          </button></li>)}</ul>}
        {hits.length > shown.length && <p className="muted">仅显示前 {MAX_HITS} 条，共 {hits.length} 条匹配 —— 多输入几个字符缩小范围。</p>}
      </div>}
    </div>;
}
