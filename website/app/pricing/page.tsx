import Link from "next/link";
import { ScrollReveal } from "@/components/scroll-reveal";

const TIERS = [
  {
    name: "Free",
    price: "0",
    period: "",
    description: "Try Ingestible with no commitment. Process documents and get structured output instantly.",
    accent: "zinc",
    features: [
      "5 documents per day",
      "1,000 tokens per document",
      "50 MB max file size",
      "Web playground only",
      "No API access",
      "No enrichment",
      "No persistent storage",
      "10 requests/minute",
      "Community support",
    ],
    cta: "Get started free",
    href: "/dashboard",
    highlighted: false,
  },
  {
    name: "Pay As You Go",
    price: "0",
    period: "",
    description: "No subscription. Pay only for what you use. Top up credits and spend them on documents.",
    accent: "emerald",
    features: [
      "$0.05 per document",
      "$0.002 per 1K tokens (enrichment)",
      "$0.01 per search query",
      "100,000 tokens per document",
      "200 MB max file size",
      "Basic enrichment included",
      "No persistent storage",
      "1 API key",
      "1,000 requests/day",
      "30 requests/minute",
      "No minimum spend",
      "Community support",
    ],
    cta: "Add credits",
    href: "/dashboard",
    highlighted: false,
  },
  {
    name: "Starter",
    price: "9.99",
    period: "/mo",
    description: "For developers who bring their own LLM keys and vector database. We handle the pipeline.",
    accent: "sky",
    features: [
      "50 documents per day",
      "100,000 tokens per document",
      "200 MB max file size",
      "BYOK \u2014 bring your own LLM keys",
      "Bring your own vector DB",
      "Full enrichment (via your keys)",
      "No persistent storage",
      "3 API keys",
      "5,000 requests/day",
      "60 requests/minute",
      "Email support",
    ],
    cta: "Start with Starter",
    href: "/dashboard",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "19.99",
    period: "/mo",
    description: "Full pipeline with our LLM quota included. No keys to manage, no infrastructure to run.",
    accent: "amber",
    features: [
      "500 documents per day",
      "500,000 tokens per document",
      "500 MB max file size",
      "LLM quota included",
      "All search enhancements",
      "Full enrichment included",
      "No persistent storage",
      "5 API keys",
      "20,000 requests/day",
      "120 requests/minute",
      "Auto-merge, HyDE, KG retrieval",
      "Priority email support",
    ],
    cta: "Go Pro",
    href: "/dashboard",
    highlighted: true,
  },
  {
    name: "Business",
    price: "29.99",
    period: "/mo",
    description: "Everything in Pro, plus managed cloud storage, corpus search, and an uptime SLA.",
    accent: "violet",
    features: [
      "Unlimited documents per day",
      "1,000,000 tokens per document",
      "1 GB max file size",
      "Persistent cloud storage included",
      "Corpus search across all documents",
      "Full enrichment included",
      "All search enhancements",
      "10 API keys",
      "50,000 requests/day",
      "200 requests/minute",
      "99.9% uptime SLA",
      "48-hour support response time",
      "Priority support",
    ],
    cta: "Start Business",
    href: "/dashboard",
    highlighted: false,
  },
];

const ACCENT_STYLES: Record<string, { border: string; badge: string; glow: string; cta: string }> = {
  zinc: {
    border: "border-zinc-800",
    badge: "text-zinc-400 border-zinc-700",
    glow: "",
    cta: "bg-zinc-800 text-zinc-200 hover:bg-zinc-700",
  },
  emerald: {
    border: "border-emerald-400/20",
    badge: "text-emerald-400 border-emerald-400/30",
    glow: "",
    cta: "bg-emerald-500 text-zinc-950 hover:bg-emerald-400",
  },
  sky: {
    border: "border-sky-400/20",
    badge: "text-sky-400 border-sky-400/30",
    glow: "",
    cta: "bg-sky-500 text-zinc-950 hover:bg-sky-400",
  },
  amber: {
    border: "border-amber-500/30",
    badge: "text-amber-400 border-amber-500/30",
    glow: "shadow-[0_0_60px_-12px_rgba(251,191,36,0.15)]",
    cta: "bg-amber-500 text-zinc-950 hover:bg-amber-400",
  },
  violet: {
    border: "border-violet-400/20",
    badge: "text-violet-400 border-violet-400/30",
    glow: "",
    cta: "bg-violet-500 text-zinc-50 hover:bg-violet-400",
  },
};

function PricingCards() {
  return (
    <section className="py-24 sm:py-32">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight">
            Simple, transparent pricing
          </h1>
          <p className="mt-4 text-lg text-zinc-400 max-w-2xl mx-auto">
            Start free, scale as you grow. Every tier includes the full ingestion pipeline &mdash;
            from parsing to search.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-5 reveal-stagger">
          {TIERS.map((tier) => {
            const style = ACCENT_STYLES[tier.accent];
            return (
              <div
                key={tier.name}
                className={`card-lift relative rounded-2xl border ${style.border} bg-zinc-900/50 p-6 flex flex-col ${style.glow} ${
                  tier.highlighted ? "ring-1 ring-amber-500/30" : ""
                }`}
              >
                {tier.highlighted && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="text-xs font-semibold px-3 py-1 rounded-full bg-amber-500 text-zinc-950">
                      Most popular
                    </span>
                  </div>
                )}

                <div className="mb-6">
                  <span
                    className={`inline-block text-xs font-semibold px-2.5 py-1 rounded-full border ${style.badge} mb-4`}
                  >
                    {tier.name}
                  </span>
                  <div className="flex items-baseline gap-1">
                    <span className="text-3xl font-bold text-zinc-50">
                      ${tier.price}
                    </span>
                    {tier.period && (
                      <span className="text-sm text-zinc-500">{tier.period}</span>
                    )}
                  </div>
                  <p className="mt-3 text-sm text-zinc-500 leading-relaxed">
                    {tier.description}
                  </p>
                </div>

                <ul className="space-y-2.5 mb-8 flex-1">
                  {tier.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2.5 text-sm text-zinc-400">
                      <CheckIcon />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>

                <Link
                  href={tier.href}
                  className={`btn-press block w-full text-center text-sm font-semibold px-6 py-3 rounded-xl transition-colors ${style.cta}`}
                >
                  {tier.cta}
                </Link>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function Enterprise() {
  return (
    <section id="enterprise" className="py-24 sm:py-32 bg-zinc-900/30 scroll-mt-20">
      <div className="max-w-5xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            On-premise &amp; Enterprise
          </h2>
          <p className="mt-4 text-zinc-400 max-w-2xl mx-auto">
            Ingestible is open source under Apache-2.0. Deploy it on your own
            infrastructure for free, with no usage limits and complete data sovereignty.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-8 reveal-stagger">
          {/* Open source self-hosting */}
          <div className="card-lift rounded-2xl border border-zinc-800 bg-zinc-900/50 p-8 flex flex-col">
            <span className="inline-block text-xs font-semibold px-2.5 py-1 rounded-full border border-zinc-700 text-zinc-400 mb-4 self-start">
              Self-hosted
            </span>
            <div className="flex items-baseline gap-1 mb-2">
              <span className="text-3xl font-bold text-zinc-50">$0</span>
              <span className="text-sm text-zinc-500">Apache-2.0</span>
            </div>
            <p className="text-sm text-zinc-500 leading-relaxed mb-6">
              Install from PyPI or run the Docker image. Use, modify, and redistribute
              it freely, including in commercial products.
            </p>

            <ul className="space-y-2.5 mb-8 flex-1">
              {[
                "Full source code (Apache-2.0)",
                "No usage limits",
                "Deploy anywhere (Docker, bare metal, K8s)",
                "All releases, no update window",
                "Community + documentation support",
                "No SLA",
              ].map((f) => (
                <li key={f} className="flex items-start gap-2.5 text-sm text-zinc-400">
                  <CheckIcon />
                  <span>{f}</span>
                </li>
              ))}
            </ul>

            <a
              href="https://pypi.org/project/ingestible/"
              className="btn-press block w-full text-center text-sm font-semibold px-6 py-3 rounded-xl bg-zinc-800 text-zinc-200 hover:bg-zinc-700 transition-colors"
            >
              Install from PyPI
            </a>
          </div>

          {/* Enterprise SLA */}
          <div className="card-lift rounded-2xl border border-amber-500/20 bg-zinc-900/50 p-8 flex flex-col shadow-[0_0_60px_-12px_rgba(251,191,36,0.1)]">
            <span className="inline-block text-xs font-semibold px-2.5 py-1 rounded-full border border-amber-500/30 text-amber-400 mb-4 self-start">
              Enterprise SLA
            </span>
            <div className="flex items-baseline gap-1 mb-2">
              <span className="text-3xl font-bold text-zinc-50">$499</span>
              <span className="text-sm text-zinc-500">/mo &middot; annual contract</span>
            </div>
            <p className="text-sm text-zinc-500 leading-relaxed mb-6">
              For organizations that need ongoing support, compliance documentation,
              and guaranteed response times for their self-hosted deployment.
            </p>

            <ul className="space-y-2.5 mb-8 flex-1">
              {[
                "Everything in self-hosted",
                "Continuous updates",
                "48-hour support response time",
                "Dedicated support channel (Slack/Teams)",
                "Custom integration assistance",
                "Security review + compliance docs",
                "SOC2, HIPAA available on request",
              ].map((f) => (
                <li key={f} className="flex items-start gap-2.5 text-sm text-zinc-400">
                  <CheckIcon />
                  <span>{f}</span>
                </li>
              ))}
            </ul>

            <a
              href="mailto:enterprise@ingestible.dev"
              className="btn-press block w-full text-center text-sm font-semibold px-6 py-3 rounded-xl bg-amber-500 text-zinc-950 hover:bg-amber-400 transition-colors"
            >
              Contact sales
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

function FAQ() {
  const faqs = [
    {
      q: "What does \"no persistent storage\" mean?",
      a: "On Free, Starter, and Pro tiers, we process your documents and return the structured output (chunks, embeddings, search results) but don't store them on our servers. You receive the data and manage storage yourself. On Business tier, we store everything in a managed vector DB so you can search across all documents at any time.",
    },
    {
      q: "What does BYOK mean on Starter?",
      a: "Bring Your Own Keys. You provide your own Anthropic, OpenAI, or other LLM API keys for the enrichment stage, and connect your own vector database (Qdrant, pgvector, or ChromaDB). We run the pipeline, you pay your own LLM and infra costs.",
    },
    {
      q: "Can I switch tiers at any time?",
      a: "Yes. Upgrades take effect immediately. Downgrades apply at the end of your current billing period.",
    },
    {
      q: "What counts as a \"document\"?",
      a: "One file upload = one document, regardless of page count. A 500-page PDF and a 2-page markdown file both count as one document.",
    },
    {
      q: "What's the difference between Business cloud and on-premise?",
      a: "Business cloud ($29.99/mo) includes managed storage, corpus search, and a 99.9% uptime SLA \u2014 we run everything. On-premise means running the open-source (Apache-2.0) release on your own infrastructure, free of charge. The Enterprise SLA subscription adds a dedicated support channel, guaranteed response times, and compliance docs.",
    },
  ];

  return (
    <section className="py-24 sm:py-32">
      <div className="max-w-3xl mx-auto px-6">
        <div className="text-center mb-12 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            Frequently asked questions
          </h2>
        </div>

        <div className="space-y-6 reveal-stagger">
          {faqs.map((faq) => (
            <div
              key={faq.q}
              className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6"
            >
              <h3 className="font-semibold text-zinc-200 mb-2">{faq.q}</h3>
              <p className="text-sm text-zinc-500 leading-relaxed">{faq.a}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function PricingPage() {
  return (
    <main>
      <PricingCards />
      <Enterprise />
      <FAQ />
      <ScrollReveal />
    </main>
  );
}

function CheckIcon() {
  return (
    <svg
      className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2.5}
      stroke="currentColor"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}
