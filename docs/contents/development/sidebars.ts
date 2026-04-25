import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

/**
 * Sidebar for the Dev section
 */
const sidebars: SidebarsConfig = {
  dev: [
    {
      type: 'doc',
      id: 'development',
      label: '🚀 Development',
    },
    {
      type: 'doc',
      id: 'requirements',
      label: '📋 Requirements',
    },
    {
      type: 'doc',
      id: 'workflow',
      label: '🔄 Development Workflow',
    },
    {
      type: 'doc',
      id: 'coding-style',
      label: '🎨 Coding Styles and Rules',
    },
    {
      type: 'doc',
      id: 'type-checking',
      label: '🔍 Type Checking with MyPy',
    },
  ],
};

export default sidebars;
