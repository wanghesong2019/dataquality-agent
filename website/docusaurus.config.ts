import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'DQAgent',
  tagline: 'Everything is an assertion; every judgment is evidence-backed',
  favicon: 'img/meerkat.png',

  // Note: `future.v4` (Rspack bundler) is left disabled — it tree-shakes mermaid's
  // d3-transition side-effect and breaks diagrams at runtime. We use webpack.

  // Production url + base path (the site is served under /<projectName>/ on GitHub Pages)
  url: 'https://wanghesong2019.github.io',
  baseUrl: '/dataquality-agent/',

  organizationName: 'wanghesong2019',
  projectName: 'dataquality-agent',

  onBrokenLinks: 'throw',

  // English is canonical. Chinese is reserved: add 'zh-CN' to `locales` and run
  // `npm run write-translations -- --locale zh-CN` once the translated content exists.
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
    path: 'i18n',
    localeConfigs: {
      en: {label: 'English', direction: 'ltr', htmlLang: 'en-US'},
    },
  },

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },
  themes: ['@docusaurus/theme-mermaid'],

  // Force d3-transition's side-effect (patches d3-selection.prototype.transition)
  // so mermaid flowchart tooltips work — see src/client/d3-transition-polyfill.js.
  clientModules: [require.resolve('./src/client/d3-transition-polyfill.js')],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl:
            'https://github.com/wanghesong2019/dataquality-agent/edit/master/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'DQAgent',
      logo: {alt: 'DQAgent', src: 'img/meerkat.png'},
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          position: 'left',
          label: 'Documentation',
        },
        {
          to: '/docs/getting-started/quickstart',
          label: 'Quickstart',
          position: 'left',
        },
        {
          href: 'https://github.com/wanghesong2019/dataquality-agent',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {label: 'Philosophy', to: '/docs/philosophy'},
            {label: 'Quickstart', to: '/docs/getting-started/quickstart'},
            {label: 'Architecture', to: '/docs/concepts/architecture'},
            {label: 'Extension points', to: '/docs/concepts/extension-points'},
          ],
        },
        {
          title: 'Reference',
          items: [
            {label: 'CLI', to: '/docs/reference/cli'},
            {label: 'Warehouse adapter', to: '/docs/reference/warehouse-adapter'},
            {label: 'Configuration', to: '/docs/reference/configuration'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: 'https://github.com/wanghesong2019/dataquality-agent'},
            {label: 'Changelog', to: '/docs/releases/changelog'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} DQAgent contributors. Licensed under Apache 2.0.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['python', 'bash', 'json', 'yaml'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
