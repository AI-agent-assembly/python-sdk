import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import remarkGfm from 'remark-gfm';
import remarkMdxCodeMeta from 'remark-mdx-code-meta';

const config: Config = {
  title: 'Agent Assembly Python SDK',
  tagline: 'Python SDK for AI Agent Assembly governance gateway integration.',
  favicon: 'img/python_logo_icon.png',

  // Set the production url of your site here
  url: 'https://ai-agent-assembly.github.io',
  // Set the /<baseUrl>/ pathname under which your site is served
  baseUrl: '/python-sdk/',
  projectName: 'python-sdk',
  organizationName: 'AI-agent-assembly',
  trailingSlash: false,

  onBrokenLinks: 'warn',
  onDuplicateRoutes: 'warn',

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  markdown: {
    mermaid: true,
    format: 'detect',
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
    mdx1Compat: {
      comments: true,
      admonitions: true,
      headingIds: true,
    },
  },

  presets: [
    [
      'classic',
      {
        docs: false,
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    [
      '@docusaurus/plugin-content-docs',
      {
        id: 'docs',
        path: 'contents/document',
        routeBasePath: 'docs',
        sidebarPath: './contents/document/sidebars.ts',
        sidebarCollapsible: true,
        showLastUpdateTime: true,
        showLastUpdateAuthor: true,
        editUrl:
          'https://github.com/AI-agent-assembly/python-sdk/tree/master/docs/',
        versions: {
          current: {
            label: 'Next',
            path: 'next',
            banner: 'unreleased',
            badge: true,
          },
        },
        includeCurrentVersion: true,
        lastVersion: 'current',
      },
    ],
    [
      '@docusaurus/plugin-content-docs',
      {
        id: 'dev',
        path: 'contents/development',
        routeBasePath: 'dev',
        sidebarPath: './contents/development/sidebars.ts',
        sidebarCollapsible: true,
        showLastUpdateTime: true,
        showLastUpdateAuthor: true,
        editUrl:
          'https://github.com/AI-agent-assembly/python-sdk/tree/master/docs/',
        versions: {
          current: {
            label: 'Next',
            path: 'next',
            banner: 'unreleased',
            badge: true,
          },
        },
        includeCurrentVersion: true,
        lastVersion: 'current',
      },
    ],
    [
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        // Options for docusaurus-search-local
        hashed: true,
        language: ['en'],
        docsRouteBasePath: ['/docs', '/dev'],
        docsDir: ['./contents/document', './contents/development'],
        highlightSearchTermsOnTargetPage: true,
        explicitSearchResultPath: true,
        docsPluginIdForPreferredVersion: 'docs',
        indexDocs: true,
        indexBlog: false,
        indexPages: true,
      },
    ],
  ],

  themes: [
    '@docusaurus/theme-mermaid',
  ],

  themeConfig: {
    // Replace with your project's social card
    image: 'img/python_logo_icon.png',
    navbar: {
      title: 'Python SDK',
      logo: {
        alt: 'My Site Logo',
        src: 'img/python_logo_icon.png',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          position: 'left',
          label: 'Docs',
          docsPluginId: 'docs',
        },
        {
          type: 'docSidebar',
          sidebarId: 'dev',
          position: 'left',
          label: 'Dev',
          docsPluginId: 'dev',
        },
        {
          type: 'custom-unifiedVersions',
          position: 'right',
          pluginIds: ['docs', 'dev'],
          pluginTitles: {
            docs: 'User Guide',
            dev: 'Developer Guide',
          },
          showBadges: true,
          showDividers: true,
          showNextLabel: true,
          showUnmaintainedLabel: true,
          dropdownItemsBefore: [],
          dropdownItemsAfter: [],
        },
        {
          href: 'https://github.com/AI-agent-assembly/python-sdk',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Docs',
              to: '/docs/next/introduction',
            },
            {
              label: 'Dev',
              to: '/dev/next',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub Issues',
              href: 'https://github.com/AI-agent-assembly/python-sdk/issues',
            },
            {
              label: 'GitHub Discussions',
              href: 'https://github.com/AI-agent-assembly/python-sdk/discussions',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'GitHub Repository',
              href: 'https://github.com/AI-agent-assembly/python-sdk',
            },
          ],
        },
      ],
      copyright: `Copyright ${new Date().getFullYear()} AI-agent-assembly.<br />Built with <a href="https://docusaurus.io/">Docusaurus</a>.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  },

  // Add redirect for homepage
  staticDirectories: ['static'],
  // Homepage redirects to documentation
  headTags: [
    {
      tagName: 'link',
      attributes: {
        rel: 'canonical',
        href: 'https://ai-agent-assembly.github.io/python-sdk/docs/introduction',
      },
    },
  ],
};

export default config;
