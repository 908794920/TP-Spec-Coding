import { useEffect, useState } from 'react';
import { theme as antdTheme, type ThemeConfig } from 'antd';

/* Single source for the workbench palette. `styles/tokens.css` keeps the same values for the
   legacy selectors that are still being migrated; change both together until migration ends. */
const palette = {
    bg: '#f3f5f7',
    surface: '#fff',
    mutedSurface: '#f7f9fb',
    text: '#202a36',
    muted: '#586776',
    border: '#d7dfe7',
    accent: '#245bb8',
    accentSoft: '#edf3ff',
    warning: '#8c5510',
    warningBg: '#fff7e8',
    danger: '#a33135',
    good: '#246b50',
    tagBg: '#f1f4f7',   // theme-only: the Tag default background has no CSS-variable counterpart
};

const fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif';
const fontFamilyCode = 'ui-monospace, SFMono-Regular, Consolas, monospace';

function buildTheme(motion: boolean): ThemeConfig {
    return {
        algorithm: [antdTheme.defaultAlgorithm, antdTheme.compactAlgorithm],
        token: {
            colorPrimary: palette.accent,
            colorBgLayout: palette.bg,
            colorBgContainer: palette.surface,
            colorBgElevated: palette.surface,
            colorText: palette.text,
            colorTextSecondary: palette.muted,
            colorBorder: palette.border,
            colorBorderSecondary: palette.border,
            colorWarning: palette.warning,
            colorWarningBg: palette.warningBg,
            colorError: palette.danger,
            colorSuccess: palette.good,
            borderRadius: 6,
            fontFamily,
            fontFamilyCode,
            motion,
        },
        components: {
            Layout: { bodyBg: palette.bg, headerBg: palette.surface, siderBg: palette.surface, headerHeight: 60, headerPadding: 0 },
            /* No `Menu` tokens: the sidebar's page menu was removed once the project tree and its
               icons covered every page, so nothing renders a Menu any more. */
            Table: { headerBg: palette.mutedSurface, headerColor: palette.muted, headerSplitColor: 'transparent', cellFontSize: 13, cellPaddingBlockSM: 8, cellPaddingInlineSM: 12 },
            Descriptions: { itemPaddingBottom: 8, colonMarginRight: 8 },
            Tag: { defaultBg: palette.tagBg, defaultColor: palette.muted },
            Card: { headerBg: 'transparent', headerFontSize: 16, paddingLG: 16 },
            Empty: { colorTextDescription: palette.muted },
        },
    };
}

/* Motion is a presentation-only concern here: when the user asks for reduced motion we disable
   Ant Design's motion tokens too, instead of only hiding CSS scroll behaviour. */
export function useWorkbenchTheme(): ThemeConfig {
    const [reducedMotion, setReducedMotion] = useState(() =>
        typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    useEffect(() => {
        const query = window.matchMedia('(prefers-reduced-motion: reduce)');
        const update = () => setReducedMotion(query.matches);
        query.addEventListener('change', update);
        return () => query.removeEventListener('change', update);
    }, []);
    return buildTheme(!reducedMotion);
}
