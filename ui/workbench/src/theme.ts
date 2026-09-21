import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { theme as antdTheme, type ThemeConfig } from 'antd';
import { normalizeTheme, resolveTheme, THEME_KEY, type ThemePreference, type ResolvedTheme } from './appearance';

interface Appearance {
    preference: ThemePreference;
    resolved: ResolvedTheme;
    setPreference: (value: ThemePreference) => void;
}
export const AppearanceContext = createContext<Appearance>({ preference: 'system', resolved: 'light', setPreference: () => {} });
export const useAppearance = () => useContext(AppearanceContext);
function storedPreference(): ThemePreference {
    try { return normalizeTheme(localStorage.getItem(THEME_KEY)); } catch { return 'system'; }
}
// 配色只维护在 tokens.css；Ant Design 与原生组件读取相同的语义变量。
function buildTheme(resolved: ResolvedTheme, motion: boolean): ThemeConfig {
    const styles = getComputedStyle(document.documentElement);
    const color = (name: string) => styles.getPropertyValue(name).trim();
    return {
        algorithm: [resolved === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm, antdTheme.compactAlgorithm],
        token: {
            colorPrimary: color('--accent'), colorBgLayout: color('--bg'), colorBgContainer: color('--surface'),
            colorBgElevated: color('--elevated'), colorText: color('--text'), colorTextSecondary: color('--muted'),
            colorBorder: color('--border'), colorBorderSecondary: color('--border'), colorWarning: color('--warning'),
            // 状态文字采用深色时，自动推导的浅底可能发灰；背景也由语义配色明确提供。
            colorWarningBg: color('--warning-bg'), colorError: color('--danger'), colorErrorBg: color('--danger-bg'),
            colorSuccess: color('--good'), colorSuccessBg: color('--good-bg'), colorInfo: color('--accent'), colorInfoBg: color('--accent-soft'),
            borderRadius: Number.parseFloat(color('--control-radius')),
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
            fontFamilyCode: 'ui-monospace, SFMono-Regular, Consolas, monospace', fontSize: 14,
            motion, motionDurationFast: '0.12s', motionDurationMid: '0.16s', motionDurationSlow: '0.18s',
        },
        components: {
            Layout: { bodyBg: color('--bg'), headerBg: color('--surface'), siderBg: color('--sidebar'), headerHeight: 52, headerPadding: 0 },
            Table: { headerBg: color('--muted-surface'), headerColor: color('--muted'), headerSplitColor: 'transparent', cellFontSize: 13, cellPaddingBlockSM: 10, cellPaddingInlineSM: 12 },
            Descriptions: { labelBg: color('--muted-surface'), itemPaddingBottom: 8 },
            Tag: { defaultBg: color('--tag-bg'), defaultColor: color('--muted') },
            Card: { headerBg: 'transparent', headerFontSize: 15, paddingLG: 16, borderRadiusLG: 8 },
            Tooltip: { colorBgSpotlight: color('--elevated'), colorTextLightSolid: color('--text') },
            Empty: { colorTextDescription: color('--muted') },
        },
    };
}
export function useWorkbenchTheme() {
    const [preference, changePreference] = useState<ThemePreference>(storedPreference);
    const [systemDark, setSystemDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches);
    const [reducedMotion, setReducedMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
    const resolved = resolveTheme(preference, systemDark);
    const [theme, setTheme] = useState(() => buildTheme(resolved, !reducedMotion));
    useLayoutEffect(() => {
        document.documentElement.dataset.theme = resolved;
        document.documentElement.style.colorScheme = resolved;
        setTheme(buildTheme(resolved, !reducedMotion));
    }, [resolved, reducedMotion]);
    useEffect(() => {
        const dark = matchMedia('(prefers-color-scheme: dark)'), reduced = matchMedia('(prefers-reduced-motion: reduce)');
        const updateDark = () => setSystemDark(dark.matches), updateMotion = () => setReducedMotion(reduced.matches);
        const storage = (event: StorageEvent) => { if (event.key === THEME_KEY || event.key === null) changePreference(normalizeTheme(event.newValue)); };
        dark.addEventListener('change', updateDark); reduced.addEventListener('change', updateMotion); window.addEventListener('storage', storage);
        return () => { dark.removeEventListener('change', updateDark); reduced.removeEventListener('change', updateMotion); window.removeEventListener('storage', storage); };
    }, []);
    const setPreference = useCallback((value: ThemePreference) => {
        const next = normalizeTheme(value);
        changePreference(next);
        try { localStorage.setItem(THEME_KEY, next); } catch { /* 无持久化能力时仍允许本页切换。 */ }
    }, []);
    const appearance = useMemo(() => ({ preference, resolved, setPreference }), [preference, resolved, setPreference]);
    return { theme, appearance };
}
