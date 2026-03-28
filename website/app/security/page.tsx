import Link from "next/link";
import { ScrollReveal } from "@/components/scroll-reveal";

/* ------------------------------------------------------------------ */
/*  Icons (Heroicons outline style, inline SVG)                        */
/* ------------------------------------------------------------------ */

function ShieldCheckIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
    </svg>
  );
}

function ServerStackIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
    </svg>
  );
}

function GlobeAltIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
    </svg>
  );
}

function LockClosedIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function EyeIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function KeyIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
    </svg>
  );
}

function CpuChipIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3M21 8.25h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3M21 15.75h-1.5M8.25 21v-1.5M15.75 21v-1.5M15.75 3v1.5m0 15V21m-7.5-2.25h7.5m-7.5 0V21m0-2.25H6a2.25 2.25 0 01-2.25-2.25V6A2.25 2.25 0 016 3.75h12A2.25 2.25 0 0120.25 6v10.5A2.25 2.25 0 0118 18.75h-2.25m-7.5 0h7.5M12 15V9m-3 3h6" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Hero                                                               */
/* ------------------------------------------------------------------ */

function Hero() {
  return (
    <section className="relative pt-32 pb-20 sm:pt-40 sm:pb-28 overflow-hidden">
      {/* Subtle glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[500px] bg-emerald-500/[0.03] rounded-full blur-3xl pointer-events-none" />

      <div className="relative max-w-4xl mx-auto px-6 text-center">
        <div className="animate-fade-in-up opacity-0">
          <span className="inline-flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full border border-emerald-500/30 text-emerald-400 mb-8">
            <ShieldCheckIcon className="w-3.5 h-3.5" />
            Security-first architecture
          </span>
        </div>

        <h1 className="text-4xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight leading-[1.08] mt-4 animate-fade-in-up opacity-0 animate-delay-100">
          Security &amp;
          <br />
          <span className="text-emerald-400">Privacy</span>
        </h1>

        <p className="mt-6 text-lg sm:text-xl text-zinc-400 max-w-2xl mx-auto leading-relaxed animate-fade-in-up opacity-0 animate-delay-200">
          Your documents contain your most sensitive knowledge. Data governance
          isn&rsquo;t an afterthought in Ingestible &mdash; it&rsquo;s a
          first-class design constraint. Deploy on your infrastructure, control
          every data flow, meet any compliance requirement.
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Your data, your infrastructure                                     */
/* ------------------------------------------------------------------ */

const INFRA_POINTS = [
  {
    icon: <ServerStackIcon className="w-5 h-5" />,
    title: "Self-hosted deployment",
    desc: "Run on your own servers via Docker, Kubernetes, or bare metal. One command to deploy, same codebase as cloud.",
  },
  {
    icon: <LockClosedIcon className="w-5 h-5" />,
    title: "Documents never leave",
    desc: "All parsing, chunking, embedding, and storage happens inside your perimeter. Zero data exfiltration surface.",
  },
  {
    icon: <ShieldCheckIcon className="w-5 h-5" />,
    title: "Air-gapped support",
    desc: "No external API calls required. Use local embedding models and skip LLM enrichment for fully isolated operation.",
  },
  {
    icon: <EyeIcon className="w-5 h-5" />,
    title: "One codebase",
    desc: "The self-hosted version is the full product \u2014 not a stripped-down or feature-gated fork. Same repo, same releases.",
  },
];

function YourInfrastructure() {
  return (
    <section className="py-24 sm:py-32 bg-zinc-900/30">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            Your data, your infrastructure
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            Deploy Ingestible wherever your security policy demands &mdash;
            on-premise, private cloud, or VPC. No vendor trust required.
          </p>
        </div>

        {/* Deployment diagram + points */}
        <div className="grid lg:grid-cols-2 gap-10 items-start">
          {/* Left: visual */}
          <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.03] p-8 reveal">
            <div className="font-mono text-sm space-y-3">
              <div className="text-zinc-500"># Deploy with Docker</div>
              <div>
                <span className="text-emerald-400">$</span>{" "}
                <span className="text-zinc-200">docker pull ghcr.io/simplyliz/ingestible:latest</span>
              </div>
              <div>
                <span className="text-emerald-400">$</span>{" "}
                <span className="text-zinc-200">docker compose up -d</span>
              </div>
              <div className="pt-3 text-zinc-500"># Or with Kubernetes</div>
              <div>
                <span className="text-emerald-400">$</span>{" "}
                <span className="text-zinc-200">helm install ingestible ./chart</span>
              </div>
              <div className="pt-3 border-t border-zinc-800 mt-3">
                <span className="text-zinc-600 text-xs">
                  All data stays within your network boundary.
                  <br />
                  No telemetry. No phone-home. No external dependencies.
                </span>
              </div>
            </div>
          </div>

          {/* Right: points */}
          <div className="space-y-5 reveal-stagger">
            {INFRA_POINTS.map((p) => (
              <div
                key={p.title}
                className="flex gap-4 items-start rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 hover:border-zinc-700 hover:bg-zinc-900/70 transition-all duration-300"
              >
                <div className="text-emerald-400 mt-0.5 shrink-0">{p.icon}</div>
                <div>
                  <h3 className="font-semibold text-zinc-100 mb-1">{p.title}</h3>
                  <p className="text-sm text-zinc-400 leading-relaxed">{p.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Data governance                                                    */
/* ------------------------------------------------------------------ */

const GOVERNANCE_CARDS = [
  {
    icon: <GlobeAltIcon />,
    title: "Data residency",
    desc: "Deploy in any region or jurisdiction. Meet GDPR, LGPD, PIPEDA, CCPA, and sector-specific residency requirements by running Ingestible where your data already lives.",
    color: "text-sky-400",
    border: "border-sky-500/30",
  },
  {
    icon: <KeyIcon />,
    title: "No vendor lock-in",
    desc: "Standard JSON output. Pluggable vector backends \u2014 ChromaDB, pgvector, or Qdrant. Switch storage, switch providers, or go fully offline at any time.",
    color: "text-amber-400",
    border: "border-amber-500/30",
  },
  {
    icon: <LockClosedIcon />,
    title: "Encryption",
    desc: "TLS for all data in transit. Configurable encryption at rest through your infrastructure\u2019s native encryption (EBS, LUKS, BitLocker) or database-level encryption.",
    color: "text-violet-400",
    border: "border-violet-500/30",
  },
  {
    icon: <ShieldCheckIcon />,
    title: "Access control",
    desc: "API key authentication, per-key rate limiting, role-based access, and full audit logging. Every document operation is traceable to a principal.",
    color: "text-emerald-400",
    border: "border-emerald-500/30",
  },
];

function DataGovernance() {
  return (
    <section className="py-24 sm:py-32">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            Data governance
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            Full control over where your data lives, how it moves, and who can
            access it.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-6 reveal-stagger">
          {GOVERNANCE_CARDS.map((c) => (
            <div
              key={c.title}
              className={`card-lift rounded-2xl border ${c.border} bg-zinc-900/40 p-6 hover:bg-zinc-900/70 transition-[background-color,border-color] duration-300`}
            >
              <div className={`${c.color} mb-4`}>{c.icon}</div>
              <h3 className="font-semibold text-zinc-100 mb-2">{c.title}</h3>
              <p className="text-sm text-zinc-400 leading-relaxed">{c.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Security practices                                                 */
/* ------------------------------------------------------------------ */

const PRACTICES = [
  {
    title: "Open source",
    desc: "Every line of the pipeline is inspectable. No proprietary black boxes processing your documents.",
  },
  {
    title: "Automated security scanning",
    desc: "CI runs Bandit (SAST), dependency vulnerability scanning, and import-level security checks on every commit.",
  },
  {
    title: "No telemetry",
    desc: "Zero analytics, tracking, or phone-home behavior. The self-hosted binary makes no outbound connections unless you configure LLM enrichment.",
  },
  {
    title: "Enterprise compliance",
    desc: "SOC 2 and HIPAA compliance documentation available for Enterprise SLA customers. Security review and custom DPA on request.",
  },
];

function SecurityPractices() {
  return (
    <section className="py-24 sm:py-32 bg-zinc-900/30">
      <div className="max-w-4xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            Security practices
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            Built in the open with defense-in-depth. Trust but verify &mdash;
            the code is right there.
          </p>
        </div>

        <div className="space-y-4 reveal-stagger">
          {PRACTICES.map((p) => (
            <div
              key={p.title}
              className="flex items-start gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 hover:border-zinc-700 hover:bg-zinc-900/70 transition-all duration-300"
            >
              <CheckIcon />
              <div>
                <h3 className="font-semibold text-zinc-100 mb-1">{p.title}</h3>
                <p className="text-sm text-zinc-400 leading-relaxed">{p.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  LLM data handling                                                  */
/* ------------------------------------------------------------------ */

const LLM_POINTS = [
  {
    icon: <CpuChipIcon />,
    title: "Minimal data exposure",
    desc: "When enrichment calls external LLM APIs (Anthropic, OpenAI), only individual chunk text is sent \u2014 never full documents, metadata, or file names.",
    color: "text-amber-400",
  },
  {
    icon: <ServerStackIcon />,
    title: "Self-hosted LLM option",
    desc: "Point the enrichment stage at your own model endpoint (vLLM, Ollama, TGI). Documents never leave your network.",
    color: "text-sky-400",
  },
  {
    icon: <KeyIcon />,
    title: "BYOK \u2014 bring your own keys",
    desc: "Your API keys, your accounts, your usage tracking. Ingestible never proxies through our servers on self-hosted deployments.",
    color: "text-violet-400",
  },
  {
    icon: <ShieldCheckIcon />,
    title: "Skip enrichment entirely",
    desc: "For maximum isolation, disable the LLM enrichment stage. You still get parsing, hierarchical chunking, embedding, and hybrid search \u2014 no external calls at all.",
    color: "text-emerald-400",
  },
];

function LLMDataHandling() {
  return (
    <section className="py-24 sm:py-32">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            LLM data handling
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            Full transparency on what leaves your infrastructure during the
            enrichment stage &mdash; and how to prevent it entirely.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-6 reveal-stagger">
          {LLM_POINTS.map((p) => (
            <div
              key={p.title}
              className="card-lift rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 hover:border-zinc-700 hover:bg-zinc-900/70 transition-[background-color,border-color] duration-300"
            >
              <div className={`${p.color} mb-4`}>{p.icon}</div>
              <h3 className="font-semibold text-zinc-100 mb-2">{p.title}</h3>
              <p className="text-sm text-zinc-400 leading-relaxed">{p.desc}</p>
            </div>
          ))}
        </div>

        {/* Data flow diagram */}
        <div className="mt-12 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-8 reveal">
          <h3 className="font-semibold text-zinc-200 mb-6 text-center text-sm uppercase tracking-wider">
            Data flow: what stays local vs. what can leave
          </h3>
          <div className="grid sm:grid-cols-2 gap-6">
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.03] p-5">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-sm font-semibold text-emerald-400">Always local</span>
              </div>
              <ul className="space-y-2">
                {[
                  "Document parsing & cleaning",
                  "Structure analysis & hierarchy",
                  "Chunking (all strategies)",
                  "Embedding (E5-large-v2)",
                  "Index building (vector + BM25)",
                  "Search & retrieval",
                  "Storage (JSON files / vector DB)",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm text-zinc-400">
                    <CheckIcon />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.03] p-5">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-2 h-2 rounded-full bg-amber-400" />
                <span className="text-sm font-semibold text-amber-400">Optional external calls</span>
              </div>
              <ul className="space-y-2">
                {[
                  "LLM enrichment (summaries, concepts)",
                  "Hypothetical question generation",
                  "Knowledge graph triple extraction",
                  "HyDE query expansion",
                  "LLM-as-judge evaluation",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm text-zinc-400">
                    <span className="w-4 h-4 mt-0.5 shrink-0 text-amber-400">
                      <svg fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
                      </svg>
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-zinc-600 mt-4">
                All optional. Disable enrichment or use a self-hosted LLM to eliminate external calls entirely.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  CTA                                                                */
/* ------------------------------------------------------------------ */

function CTA() {
  return (
    <section className="py-24 sm:py-32 bg-zinc-900/30">
      <div className="max-w-3xl mx-auto px-6 text-center reveal">
        <ShieldCheckIcon className="w-10 h-10 text-emerald-400 mx-auto mb-6" />
        <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
          Ready to deploy on your infrastructure?
        </h2>
        <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
          Get started with a single Docker command, or contact our team for
          enterprise deployment planning, custom SLAs, and compliance
          documentation.
        </p>
        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            href="/docs/Deployment"
            className="btn-press w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-xl bg-emerald-500 text-zinc-950 font-semibold text-sm hover:bg-emerald-400 transition-colors"
          >
            Deployment guide
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
            </svg>
          </Link>
          <a
            href="mailto:enterprise@ingestible.dev"
            className="btn-press w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-xl border border-zinc-700 text-zinc-200 font-semibold text-sm hover:border-zinc-500 hover:bg-zinc-900 transition-colors"
          >
            Contact enterprise sales
          </a>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function SecurityPage() {
  return (
    <main>
      <Hero />
      <YourInfrastructure />
      <DataGovernance />
      <SecurityPractices />
      <LLMDataHandling />
      <CTA />
      <ScrollReveal />
    </main>
  );
}
