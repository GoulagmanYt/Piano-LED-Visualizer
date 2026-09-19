(function () {
    const THEME_STORAGE_KEY = 'plv-web-theme';
    const DEFAULT_THEME = Object.freeze({
        web_theme_mode: 'dark',
        web_theme_preset: 'aurora',
        web_theme_accent: '#22d3ee',
        web_theme_background_color: '#334155',
        web_theme_surface_color: '#cbd5e1',
        web_theme_icon_color: '#94a3b8',
        web_theme_badge_color: '#0f766e',
        web_theme_badge_text_color: '#f8fafc',
        web_theme_surface: 'glass',
        web_theme_radius: 'rounded',
        web_theme_glow: 'normal',
        web_theme_contrast: 'balanced',
        web_theme_background: 'ambient'
    });
    const THEME_OPTIONS = Object.freeze({
        web_theme_mode: ['dark', 'light', 'auto'],
        web_theme_preset: ['aurora', 'ember', 'forest', 'mono', 'ocean', 'sunrise'],
        web_theme_surface: ['glass', 'solid', 'flat'],
        web_theme_radius: ['soft', 'rounded', 'crisp'],
        web_theme_glow: ['subtle', 'normal', 'vivid'],
        web_theme_contrast: ['balanced', 'strong'],
        web_theme_background: ['ambient', 'mesh', 'minimal', 'stage']
    });
    const THEME_LABEL_KEYS = Object.freeze({
        web_theme_mode: { dark: 'theme_mode_dark', light: 'theme_mode_light', auto: 'theme_mode_auto' },
        web_theme_preset: {
            aurora: 'theme_preset_aurora',
            ember: 'theme_preset_ember',
            forest: 'theme_preset_forest',
            mono: 'theme_preset_mono',
            ocean: 'theme_preset_ocean',
            sunrise: 'theme_preset_sunrise'
        },
        web_theme_surface: { glass: 'theme_surface_glass', solid: 'theme_surface_solid', flat: 'theme_surface_flat' },
        web_theme_radius: { soft: 'theme_radius_soft', rounded: 'theme_radius_rounded', crisp: 'theme_radius_crisp' },
        web_theme_glow: { subtle: 'theme_glow_subtle', normal: 'theme_glow_normal', vivid: 'theme_glow_vivid' },
        web_theme_contrast: { balanced: 'theme_contrast_balanced', strong: 'theme_contrast_strong' },
        web_theme_background: {
            ambient: 'theme_background_ambient',
            mesh: 'theme_background_mesh',
            minimal: 'theme_background_minimal',
            stage: 'theme_background_stage'
        }
    });

    let mediaQueryBound = false;

    function normalizeHexColor(value, fallback = DEFAULT_THEME.web_theme_accent) {
        if (!value) {
            return fallback;
        }

        let normalized = String(value).trim();
        if (!normalized.startsWith('#')) {
            normalized = '#' + normalized;
        }

        return /^#[0-9a-fA-F]{6}$/.test(normalized) ? normalized.toLowerCase() : fallback;
    }

    function hexToRgbTriplet(hex) {
        const normalized = normalizeHexColor(hex);
        return [
            parseInt(normalized.slice(1, 3), 16),
            parseInt(normalized.slice(3, 5), 16),
            parseInt(normalized.slice(5, 7), 16)
        ].join(', ');
    }

    function shouldUseDarkTheme(mode) {
        if (mode === 'light') {
            return false;
        }
        if (mode === 'auto') {
            return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        }
        return true;
    }

    function readStoredTheme() {
        try {
            const raw = localStorage.getItem(THEME_STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (error) {
            return {};
        }
    }

    function persistTheme(theme) {
        try {
            localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(theme));
        } catch (error) {
            console.warn('Unable to persist theme settings:', error);
        }
    }

    function extractThemeKeys(source) {
        if (!source || typeof source !== 'object') {
            return {};
        }
        const out = {};
        const allKeys = Object.keys(DEFAULT_THEME);
        allKeys.forEach(function (key) {
            if (Object.prototype.hasOwnProperty.call(source, key)) {
                out[key] = source[key];
            }
        });
        return out;
    }

    function normalizeTheme(source) {
        const filtered = extractThemeKeys(source);
        const theme = {
            ...DEFAULT_THEME,
            ...filtered
        };

        Object.keys(THEME_OPTIONS).forEach(function (key) {
            const allowed = THEME_OPTIONS[key];
            theme[key] = allowed.includes(theme[key]) ? theme[key] : DEFAULT_THEME[key];
        });

        theme.web_theme_accent = normalizeHexColor(theme.web_theme_accent);
        theme.web_theme_background_color = normalizeHexColor(theme.web_theme_background_color, DEFAULT_THEME.web_theme_background_color);
        theme.web_theme_surface_color = normalizeHexColor(theme.web_theme_surface_color, DEFAULT_THEME.web_theme_surface_color);
        theme.web_theme_icon_color = normalizeHexColor(theme.web_theme_icon_color, DEFAULT_THEME.web_theme_icon_color);
        theme.web_theme_badge_color = normalizeHexColor(theme.web_theme_badge_color, DEFAULT_THEME.web_theme_badge_color);
        theme.web_theme_badge_text_color = normalizeHexColor(theme.web_theme_badge_text_color, DEFAULT_THEME.web_theme_badge_text_color);
        return theme;
    }

    function localizeThemeLabel(groupKey, value, fallback) {
        const translationKey = THEME_LABEL_KEYS[groupKey] && THEME_LABEL_KEYS[groupKey][value];
        if (translationKey && typeof window.translate === 'function') {
            const translated = window.translate(translationKey);
            if (translated && translated !== translationKey) {
                return translated;
            }
        }
        return fallback;
    }

    function applyThemeToDom(theme) {
        const root = document.documentElement;
        root.classList.toggle('dark', shouldUseDarkTheme(theme.web_theme_mode));
        root.dataset.themeMode = theme.web_theme_mode;
        root.dataset.themePreset = theme.web_theme_preset;
        root.dataset.themeSurface = theme.web_theme_surface;
        root.dataset.themeRadius = theme.web_theme_radius;
        root.dataset.themeGlow = theme.web_theme_glow;
        root.dataset.themeContrast = theme.web_theme_contrast;
        root.dataset.themeBackground = theme.web_theme_background;
        root.style.setProperty('--theme-accent-rgb', hexToRgbTriplet(theme.web_theme_accent));
        root.style.setProperty('--theme-background-rgb', hexToRgbTriplet(theme.web_theme_background_color));
        root.style.setProperty('--theme-surface-rgb', hexToRgbTriplet(theme.web_theme_surface_color));
        root.style.setProperty('--theme-icon-rgb', hexToRgbTriplet(theme.web_theme_icon_color));
        root.style.setProperty('--theme-badge-rgb', hexToRgbTriplet(theme.web_theme_badge_color));
        root.style.setProperty('--theme-badge-text-rgb', hexToRgbTriplet(theme.web_theme_badge_text_color));
        root.style.setProperty('--theme-meta-color', theme.web_theme_background_color);
    }

    function updateMetaThemeColor() {
        const metaThemeColor = document.querySelector('meta[name="theme-color"]');
        if (!metaThemeColor) {
            return;
        }

        const rootStyles = getComputedStyle(document.documentElement);
        const themeColor = rootStyles.getPropertyValue('--theme-meta-color').trim()
            || rootStyles.getPropertyValue('--app-bg').trim()
            || '#0f172a';
        metaThemeColor.setAttribute('content', themeColor);
    }

    function refreshThemeAwareCharts() {
        if (typeof window.getThemeRgba !== 'function') {
            return;
        }

        const cpuChart = window.cpuChart;
        if (cpuChart && cpuChart.data && cpuChart.data.datasets && cpuChart.data.datasets[0]) {
            cpuChart.data.datasets[0].borderColor = window.getThemeRgba('--theme-accent-rgb', 0.9);
            cpuChart.data.datasets[0].backgroundColor = window.getThemeRgba('--theme-accent-rgb', 0.18);
            cpuChart.update('none');
        }

        const ledFpsChart = window.ledFpsChart;
        if (ledFpsChart && ledFpsChart.data && ledFpsChart.data.datasets && ledFpsChart.data.datasets[0]) {
            ledFpsChart.data.datasets[0].borderColor = window.getThemeRgba('--theme-secondary-rgb', 0.9);
            ledFpsChart.data.datasets[0].backgroundColor = window.getThemeRgba('--theme-secondary-rgb', 0.18);
            ledFpsChart.update('none');
        }
    }

    function syncGroupButtons(theme) {
        document.querySelectorAll('[data-theme-group]').forEach(function (group) {
            const settingName = group.getAttribute('data-theme-group');
            const selectedValue = theme[settingName];

            group.querySelectorAll('[data-theme-value]').forEach(function (button) {
                const isActive = button.getAttribute('data-theme-value') === selectedValue;
                button.classList.toggle('is-active', isActive);
                button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
            });
        });
    }

    function syncThemeControls(theme) {
        Object.keys(DEFAULT_THEME).forEach(function (key) {
            const field = document.getElementById(key);
            if (field) {
                field.value = theme[key];
            }
        });

        const accentInput = document.getElementById('web_theme_accent');
        if (accentInput) {
            accentInput.value = theme.web_theme_accent;
        }

        const accentTextInput = document.getElementById('web_theme_accent_hex');
        if (accentTextInput) {
            accentTextInput.value = theme.web_theme_accent;
        }

        ['background_color', 'surface_color', 'icon_color', 'badge_color', 'badge_text_color'].forEach(function (suffix) {
            const baseKey = 'web_theme_' + suffix;
            const picker = document.getElementById(baseKey);
            if (picker) {
                picker.value = theme[baseKey];
            }

            const textField = document.getElementById(baseKey + '_hex');
            if (textField) {
                textField.value = theme[baseKey];
            }
        });

        document.querySelectorAll('[data-theme-preset-card]').forEach(function (card) {
            const isActive = card.getAttribute('data-theme-preset-card') === theme.web_theme_preset;
            card.classList.toggle('is-active', isActive);
            card.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        document.querySelectorAll('.theme-swatch').forEach(function (swatch) {
            const swatchColor = normalizeHexColor(swatch.style.getPropertyValue('--swatch-color'));
            const isActive = swatchColor === theme.web_theme_accent;
            swatch.classList.toggle('is-active', isActive);
            swatch.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        syncGroupButtons(theme);

        const previewMode = document.getElementById('theme_preview_mode');
        if (previewMode) {
            previewMode.textContent = localizeThemeLabel('web_theme_mode', theme.web_theme_mode, theme.web_theme_mode);
        }

        const previewPreset = document.getElementById('theme_preview_preset');
        if (previewPreset) {
            previewPreset.textContent = localizeThemeLabel('web_theme_preset', theme.web_theme_preset, theme.web_theme_preset);
        }

        const previewSurface = document.getElementById('theme_preview_surface');
        if (previewSurface) {
            previewSurface.textContent = localizeThemeLabel('web_theme_surface', theme.web_theme_surface, theme.web_theme_surface);
        }

        const previewBackground = document.getElementById('theme_preview_background');
        if (previewBackground) {
            previewBackground.textContent = localizeThemeLabel('web_theme_background', theme.web_theme_background, theme.web_theme_background);
        }
    }

    function bindAutoThemeListener() {
        if (mediaQueryBound || !window.matchMedia) {
            return;
        }

        const query = window.matchMedia('(prefers-color-scheme: dark)');
        const updateThemeOnSystemChange = function () {
            if (window.currentThemeSettings && window.currentThemeSettings.web_theme_mode === 'auto') {
                window.applyThemeSettings(window.currentThemeSettings, {
                    persist: false,
                    syncControls: true,
                    readStored: false
                });
            }
        };

        if (typeof query.addEventListener === 'function') {
            query.addEventListener('change', updateThemeOnSystemChange);
        } else if (typeof query.addListener === 'function') {
            query.addListener(updateThemeOnSystemChange);
        }

        mediaQueryBound = true;
    }

    function persistThemeKeys(theme, keys) {
        if (typeof window.change_setting !== 'function') {
            return;
        }

        keys.forEach(function (key) {
            window.change_setting(key, theme[key]);
        });
    }

    function updateThemeWith(partialTheme, options) {
        const theme = window.applyThemeSettings({
            ...(window.currentThemeSettings || DEFAULT_THEME),
            ...(partialTheme || {})
        }, options);

        persistThemeKeys(theme, Object.keys(partialTheme || {}));
        return theme;
    }

    window.getThemeCssVar = function (name, fallback = '') {
        const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return value || fallback;
    };

    window.getThemeRgba = function (name, alpha) {
        const rgbValue = window.getThemeCssVar(name, '34, 211, 238');
        return 'rgba(' + rgbValue + ', ' + alpha + ')';
    };

    window.applyThemeSettings = function (source, options = {}) {
        const stored = options.readStored === false ? {} : readStoredTheme();
        const theme = normalizeTheme({
            ...DEFAULT_THEME,
            ...stored,
            ...extractThemeKeys(window.currentThemeSettings || {}),
            ...extractThemeKeys(source || {})
        });

        applyThemeToDom(theme);
        window.currentThemeSettings = theme;

        if (options.persist !== false) {
            persistTheme(theme);
        }

        if (options.syncControls !== false) {
            syncThemeControls(theme);
        }

        updateMetaThemeColor();
        refreshThemeAwareCharts();
        bindAutoThemeListener();

        return theme;
    };

    window.setWebThemeMode = function (value) {
        return updateThemeWith({ web_theme_mode: value });
    };

    window.setWebThemePreset = function (value) {
        return updateThemeWith({ web_theme_preset: value });
    };

    window.setWebThemeAccent = function (value) {
        return updateThemeWith({ web_theme_accent: value });
    };

    window.previewWebThemeAccent = function (value) {
        return window.previewWebThemeColor('web_theme_accent', value);
    };

    window.setWebThemeColor = function (settingName, value) {
        const update = {};
        update[settingName] = value;
        return updateThemeWith(update);
    };

    window.previewWebThemeColor = function (settingName, value) {
        return window.applyThemeSettings({
            ...(window.currentThemeSettings || DEFAULT_THEME),
            [settingName]: value
        }, {
            persist: false,
            syncControls: false,
            readStored: false
        });
    };

    window.setWebThemeSurface = function (value) {
        return updateThemeWith({ web_theme_surface: value });
    };

    window.setWebThemeRadius = function (value) {
        return updateThemeWith({ web_theme_radius: value });
    };

    window.setWebThemeGlow = function (value) {
        return updateThemeWith({ web_theme_glow: value });
    };

    window.setWebThemeContrast = function (value) {
        return updateThemeWith({ web_theme_contrast: value });
    };

    window.setWebThemeBackground = function (value) {
        return updateThemeWith({ web_theme_background: value });
    };

    window.resetWebThemeSettings = function () {
        const theme = window.applyThemeSettings(DEFAULT_THEME, {
            persist: true,
            syncControls: true,
            readStored: false
        });
        persistThemeKeys(theme, Object.keys(DEFAULT_THEME));
        return theme;
    };

    window.initializeThemeControls = function () {
        syncThemeControls(window.currentThemeSettings || window.applyThemeSettings(
            window.initialThemeSettings || DEFAULT_THEME,
            {
                persist: false,
                syncControls: false,
                readStored: false
            }
        ));
    };

    window.initializeAppearancePage = function () {
        window.initializeThemeControls();
    };

    window.applyThemeSettings(
        window.currentThemeSettings || window.initialThemeSettings || DEFAULT_THEME,
        {
            persist: false,
            syncControls: false,
            readStored: false
        }
    );
})();
