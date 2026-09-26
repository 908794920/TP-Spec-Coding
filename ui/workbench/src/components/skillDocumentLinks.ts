export interface SkillDocumentLocation { path: string; hash: string }

/** Resolve within one source root, never the Base of a different skill. Encode the current filename
 * before URL resolution so literal %, # and ? in filenames cannot become URL syntax. The sentinel
 * also detects traversal that URL would otherwise silently clamp at its root. */
export function resolveSkillLink(currentPath: string, href: string): SkillDocumentLocation {
    const relative = href.replace(/\\/g, '/');
    if (!relative || /^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(relative)) throw new Error('仅支持本来源内的相对 Markdown 链接');
    const prefix = '/__skill_source__/';
    const base = new URL(prefix + currentPath.split('/').map(encodeURIComponent).join('/'), 'https://skill-doc.invalid');
    const target = new URL(relative, base);
    if (target.origin !== base.origin || !target.pathname.startsWith(prefix) || target.search) {
        throw new Error('链接超出当前来源，或包含不支持的查询参数');
    }
    const path = decodeURIComponent(target.pathname.slice(prefix.length));
    const parts: string[] = [];
    for (const part of path.replace(/\\/g, '/').split('/')) {
        if (part === '..') {
            if (!parts.length) throw new Error('链接超出当前来源');
            parts.pop();
        } else if (part && part !== '.') parts.push(part);
    }
    const normalized = parts.join('/');
    if (!/\.md$/i.test(normalized)) throw new Error('仅支持阅读 Markdown；图片和脚本不在此处执行或预览');
    return { path: normalized, hash: decodeURIComponent(target.hash.slice(1)) };
}
