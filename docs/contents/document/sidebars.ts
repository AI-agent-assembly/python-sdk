import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

/**
 * Sidebar for the Docs section
 */
const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'doc',
      id: 'introduction',
      label: '📖 Introduction',
    },
    {
      type: 'category',
      label: '🤟 Quickly Start',
      collapsed: false,
      items: [
        {
          type: 'doc',
          id: 'quick-start/quick-start',
          label: '⚡ Quick Start',
        },
        {
          type: 'doc',
          id: 'quick-start/requirements',
          label: '📋 Requirements',
        },
        {
          type: 'doc',
          id: 'quick-start/installation',
          label: '💾 Installation',
        },
        {
          type: 'doc',
          id: 'quick-start/how-to-run',
          label: '▶️ How to Run',
        },
      ],
    },
    {
      type: 'category',
      label: '🧑‍💻 API References',
      items: [
        {
          type: 'doc',
          id: 'api-references/api-references',
          label: '📚 API References',
        },
        // {
        //   type: 'doc',
        //   id: 'server-references/environment-configuration',
        //   label: '🌍 Environment Configuration',
        // },
        // {
        //   type: 'doc',
        //   id: 'server-references/logging-configuration',
        //   label: '📋 Logging Configuration',
        // },
        // {
        //   type: 'doc',
        //   id: 'server-references/cli-execution-methods',
        //   label: '⌨️ CLI Execution Methods',
        // },
        // {
        //   type: 'doc',
        //   id: 'server-references/deployment-guide',
        //   label: '🚀 Deployment Guide',
        // },
        // {
        //   type: 'category',
        //   label: '🌐 Web Server',
        //   items: [
        //     {
        //       type: 'doc',
        //       id: 'server-references/web-server/web-apis',
        //       label: '🌐 Web APIs',
        //     },
        //     {
        //       type: 'category',
        //       label: '🔌 End-points',
        //       items: [
        //         {
        //           type: 'doc',
        //           id: 'server-references/web-server/end-points/web-api-health-check',
        //           label: '💓 Health Check',
        //         },
        //       ],
        //     },
        //   ],
        // },
      ],
    },
    {
      type: 'doc',
      id: 'changelog',
      label: '📝 Changelog',
    },
  ],
};

export default sidebars;
