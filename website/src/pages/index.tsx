import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

const PILLARS = [
  {
    title: 'Detect',
    body: 'Three layers — L0 deterministic rules, L1 statistical observability, L2 LLM semantics — surface what rules alone miss.',
  },
  {
    title: 'Attribute',
    body: 'A supervisor triages each anomaly to a focused specialist (lineage, SQL, cases) and aggregates a root-cause diagnosis.',
  },
  {
    title: 'Remediate',
    body: 'An executor and a critic propose fixes; high-risk fixes wait behind a human approval gate before anything touches data.',
  },
];

const QUICKSTART = `pip install dataquality-agent

# 1. scaffold sample data + config
dqagent init --dir ./demo

# 2. no-LLM detection (L0 + L1), no API key needed
dqagent detect --dir ./demo

# 3. full patrol — inspect → attribute → remediate → approve
dqagent run --dir ./demo`;

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout description="Agentic data quality — an LLM multi-agent pipeline that detects, attributes, and remediates data issues with a human approval gate.">
      <header className={styles.hero}>
        <div className={styles.heroText}>
          <span className={styles.eyebrow}>Open source · Agentic data quality</span>
          <Heading as="h1" className={styles.title}>
            Inspect. Attribute. Remediate.
          </Heading>
          <p className={styles.subtitle}>
            DataAgent upgrades rule-and-manual data governance into an LLM multi-agent
            pipeline that detects issues, traces their root cause, and closes the loop —
            with a human approval gate on every high-risk fix.
          </p>
          <div className={styles.actions}>
            <Link
              className="button button--primary button--lg"
              to="/docs/getting-started/quickstart">
              Get started in 5 minutes
            </Link>
            <Link
              className="button button--secondary button--lg"
              to="/docs/concepts/architecture">
              Read the architecture
            </Link>
          </div>
        </div>
        <div className={styles.terminal}>
          <div className={styles.terminalBar}>
            <span />
            <span />
            <span />
          </div>
          <pre className={styles.terminalBody}>{QUICKSTART}</pre>
        </div>
      </header>

      <main>
        <section className={styles.pillars}>
          {PILLARS.map((p) => (
            <div key={p.title} className={styles.pillar}>
              <Heading as="h3">{p.title}</Heading>
              <p>{p.body}</p>
            </div>
          ))}
        </section>

        <section className={styles.why}>
          <Heading as="h2">Why DataAgent</Heading>
          <div className={styles.whyGrid}>
            <div>
              <Heading as="h3">Closes the loop others leave open</Heading>
              <p>
                Traditional DQ tools — Great Expectations, Soda, Deequ, Griffin — detect but
                don't attribute root cause or remediate. DataAgent turns "a check failed"
                into "here's why, here's the fix, and here's the approval gate."
              </p>
            </div>
            <div>
              <Heading as="h3">Pluggable by design</Heading>
              <p>
                Four seams — warehouse adapter, detector, remediation policy, case store —
                so you connect your warehouse and teach it your rules without forking the core.
              </p>
            </div>
            <div>
              <Heading as="h3">Proposes, never executes</Heading>
              <p>
                At runtime DataAgent only proposes. High-risk fixes wait for a human, and every
                plan is verified offline against a cloned warehouse.
              </p>
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
