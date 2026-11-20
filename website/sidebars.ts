import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      items: ['getting-started/quickstart'],
    },
    {
      type: 'category',
      label: 'Concepts',
      collapsed: false,
      items: [
        'concepts/architecture',
        'concepts/core-flow',
        'concepts/extension-points',
        'concepts/why-propose-only',
      ],
    },
    {
      type: 'category',
      label: 'How-to Guides',
      items: [
        'how-to/connect-a-warehouse',
        'how-to/write-a-detector',
        'how-to/define-remediation',
        'how-to/deploy',
        'how-to/run-eval-on-your-warehouse',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      items: [
        'reference/cli',
        'reference/warehouse-adapter',
        'reference/detectors',
        'reference/configuration',
      ],
    },
    {
      type: 'category',
      label: 'Releases',
      items: ['releases/changelog'],
    },
  ],
};

export default sidebars;
