const GITHUB_URL = "https://github.com/SimplyLiz/Ingestible";
const PYPI_URL = "https://pypi.org/project/ingestible";
const DOCS_URL = "/docs/Introduction";

function Hero() {
  return (
    <section className="relative pt-32 pb-24 sm:pt-40 sm:pb-32 overflow-hidden">
      {/* Glow effect — parallax on scroll in supporting browsers */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[600px] bg-amber-500/[0.04] rounded-full blur-3xl pointer-events-none hero-glow-parallax" />

      <div className="relative max-w-4xl mx-auto px-6 text-center">
        <div className="animate-fade-in-up opacity-0">
          <a
            href={`${GITHUB_URL}/releases`}
            className="inline-flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full border border-zinc-800 text-zinc-400 hover:border-amber-500/40 hover:text-amber-400 transition-colors mb-8"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-subtle" />
            v1.4.0 &mdash; Now open source under Apache-2.0
          </a>
        </div>

        <h1 className="text-4xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight leading-[1.08] mt-4 animate-fade-in-up opacity-0 animate-delay-100">
          Documents in.
          <br />
          <span className="text-amber-400">Knowledge out.</span>
        </h1>

        <p className="mt-6 text-lg sm:text-xl text-zinc-400 max-w-2xl mx-auto leading-relaxed animate-fade-in-up opacity-0 animate-delay-200">
          Turn documents into token-efficient, searchable knowledge stores for
          AI. Hybrid search across vector, BM25, and concept indexes &mdash;
          each query costs ~1,000 tokens instead of 90,000.
        </p>

        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4 animate-fade-in-up opacity-0 animate-delay-300">
          <a
            href="#install"
            className="btn-press w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-xl bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 transition-colors"
          >
            Get started
            <ArrowRightIcon />
          </a>
          <a
            href={GITHUB_URL}
            className="btn-press w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-xl border border-zinc-700 text-zinc-200 font-semibold text-sm hover:border-zinc-500 hover:bg-zinc-900 transition-colors"
          >
            <GithubIcon />
            View on GitHub
          </a>
        </div>

        {/* Token comparison */}
        <div className="mt-16 animate-fade-in-up opacity-0 animate-delay-400">
          <div className="inline-flex flex-col sm:flex-row gap-4 sm:gap-0 sm:divide-x divide-zinc-800 rounded-2xl border border-zinc-800 bg-zinc-900/50 p-6 sm:p-0">
            <TokenStat
              label="513-page book"
              before="92,598"
              after="~1,317"
              reduction="99%"
            />
            <TokenStat
              label="55-page paper"
              before="4,975"
              after="~585"
              reduction="88%"
            />
          </div>
        </div>
      </div>
    </section>
  );
}

function TokenStat({
  label,
  before,
  after,
  reduction,
}: {
  label: string;
  before: string;
  after: string;
  reduction: string;
}) {
  return (
    <div className="sm:px-10 sm:py-6 text-center">
      <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">
        {label}
      </p>
      <div className="flex items-center justify-center gap-3">
        <span className="text-zinc-500 line-through text-sm font-mono">
          {before}
        </span>
        <ArrowRightIcon className="text-amber-400 w-3.5 h-3.5" />
        <span className="text-amber-400 font-bold text-lg font-mono">
          {after}
        </span>
        <span className="text-xs font-medium text-emerald-400">
          -{reduction}
        </span>
      </div>
      <p className="text-xs text-zinc-600 mt-1">tokens per query</p>
    </div>
  );
}

const FEATURES = [
  {
    title: "25+ formats",
    description:
      "PDF, DOCX, HTML, EPUB, PPTX, XLSX, CSV, Markdown, audio, video, images, email, ZIP archives, and more.",
    icon: <FileIcon />,
    color: "text-amber-400",
  },
  {
    title: "4-level hierarchy",
    description:
      "Document overview, chapters, sections, passages. No mid-paragraph splits. Tables and code stay atomic.",
    icon: <LayersIcon />,
    color: "text-sky-400",
  },
  {
    title: "Hybrid search",
    description:
      "Vector + BM25 + concept index fused with RRF. Optional cross-encoder reranking, HyDE, and knowledge graph retrieval.",
    icon: <SearchIcon />,
    color: "text-violet-400",
  },
  {
    title: "LLM enrichment",
    description:
      "Summaries, concepts, hypothetical questions, entities, and knowledge graph triples. Bottom-up from passages to document.",
    icon: <SparklesIcon />,
    color: "text-emerald-400",
  },
  {
    title: "Production ready",
    description:
      "Rate limiting, Prometheus metrics, auth middleware, background ingestion with checkpoint/resume, Docker-ready.",
    icon: <ServerIcon />,
    color: "text-amber-400",
  },
  {
    title: "MCP + API + CLI",
    description:
      "Three entry points. REST API with FastAPI, CLI for automation, MCP server for AI agent integration.",
    icon: <TerminalIcon />,
    color: "text-sky-400",
  },
];

function Features() {
  return (
    <section id="features" className="py-24 sm:py-32">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            Everything you need for RAG
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            From parsing to search, Ingestible handles the full pipeline so you
            can focus on building your AI application.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6 reveal-stagger">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="card-lift group rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 hover:border-zinc-700 hover:bg-zinc-900/70 transition-[background-color,border-color] duration-300"
            >
              <div className={`${f.color} mb-4`}>{f.icon}</div>
              <h3 className="font-semibold text-zinc-100 mb-2">{f.title}</h3>
              <p className="text-sm text-zinc-400 leading-relaxed">
                {f.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const FORMAT_CATEGORIES = [
  {
    name: "Documents",
    color: "text-amber-400",
    borderColor: "border-amber-500/30",
    formats: ["PDF", "DOCX", "PPTX", "XLSX", "CSV", "EPUB"],
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
    ),
  },
  {
    name: "Web & Markup",
    color: "text-sky-400",
    borderColor: "border-sky-500/30",
    formats: ["HTML", "Markdown", "RST", "AsciiDoc", "XML", "JSON/JSONL"],
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
      </svg>
    ),
  },
  {
    name: "Media",
    color: "text-violet-400",
    borderColor: "border-violet-500/30",
    formats: ["MP3", "WAV", "FLAC", "MP4", "MKV", "AVI", "PNG", "JPG", "TIFF"],
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m-3.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-1.5A1.125 1.125 0 0118 18.375M20.625 4.5H3.375m17.25 0c.621 0 1.125.504 1.125 1.125M20.625 4.5h-1.5C18.504 4.5 18 5.004 18 5.625m3.75 0v1.5c0 .621-.504 1.125-1.125 1.125M3.375 4.5c-.621 0-1.125.504-1.125 1.125M3.375 4.5h1.5C5.496 4.5 6 5.004 6 5.625m-3.75 0v1.5c0 .621.504 1.125 1.125 1.125m0 0h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m1.5-3.75C5.496 8.25 6 7.746 6 7.125v-1.5M4.875 8.25C5.496 8.25 6 8.754 6 9.375v1.5m0-5.25v5.25m0-5.25C6 5.004 6.504 4.5 7.125 4.5h9.75c.621 0 1.125.504 1.125 1.125m1.125 2.625h1.5m-1.5 0A1.125 1.125 0 0118 7.125v-1.5m1.125 2.625c-.621 0-1.125.504-1.125 1.125v1.5m2.625-2.625c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125M18 5.625v5.25M7.125 12h9.75m-9.75 0A1.125 1.125 0 016 10.875M7.125 12C6.504 12 6 12.504 6 13.125m0-2.25c0 .621.504 1.125 1.125 1.125M18 10.875c0 .621-.504 1.125-1.125 1.125M18 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125m-12 5.25v-5.25m0 5.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125m-12 0v-1.5c0-.621-.504-1.125-1.125-1.125M18 18.375v-5.25m0 5.25v-1.5c0-.621.504-1.125 1.125-1.125M18 13.125v1.5c0 .621.504 1.125 1.125 1.125M18 13.125c0-.621.504-1.125 1.125-1.125M6 13.125v1.5c0 .621-.504 1.125-1.125 1.125M6 13.125C6 12.504 5.496 12 4.875 12m-1.5 0h1.5m-1.5 0c-.621 0-1.125-.504-1.125-1.125v-1.5c0-.621.504-1.125 1.125-1.125m1.5 2.625c0-.621-.504-1.125-1.125-1.125M19.125 12h1.5m0 0c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 2.625h-1.5" />
      </svg>
    ),
  },
  {
    name: "Other",
    color: "text-emerald-400",
    borderColor: "border-emerald-500/30",
    formats: ["Email (EML/MSG)", "ZIP Archives", "Plain Text"],
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
      </svg>
    ),
  },
];

function SupportedFormats() {
  return (
    <section id="formats" className="py-24 sm:py-32 bg-zinc-900/30">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            25+ formats supported
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            Drop in documents, media, archives, or markup. Ingestible handles
            parsing, cleaning, and structure extraction automatically.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6 reveal-stagger">
          {FORMAT_CATEGORIES.map((cat) => (
            <div
              key={cat.name}
              className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5 hover:border-zinc-700 hover:bg-zinc-900/70 transition-all duration-300"
            >
              <div className="flex items-center gap-2.5 mb-4">
                <span className={cat.color}>{cat.icon}</span>
                <h3 className="font-semibold text-zinc-100 text-sm">
                  {cat.name}
                </h3>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {cat.formats.map((fmt) => (
                  <span
                    key={fmt}
                    className={`text-xs font-medium px-2.5 py-1 rounded-lg border ${cat.borderColor} bg-zinc-950/40 text-zinc-300`}
                  >
                    {fmt}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const PIPELINE_STAGES = [
  {
    name: "Parse",
    desc: "Format-specific extraction to clean markdown. PDF uses IBM Docling for deep layout analysis.",
    color: "border-amber-500/50 bg-amber-500/5",
    dot: "bg-amber-400",
  },
  {
    name: "Structure",
    desc: "Builds hierarchy tree from TOC, heading patterns, or page range heuristics.",
    color: "border-sky-500/50 bg-sky-500/5",
    dot: "bg-sky-400",
  },
  {
    name: "Chunk",
    desc: "4-level split (L0-L3). Tables and code blocks stay atomic. ~10% overlap between chunks.",
    color: "border-violet-500/50 bg-violet-500/5",
    dot: "bg-violet-400",
  },
  {
    name: "Enrich",
    desc: "Bottom-up LLM pass generates summaries, concepts, hypothetical questions, and entities.",
    color: "border-emerald-500/50 bg-emerald-500/5",
    dot: "bg-emerald-400",
  },
  {
    name: "Embed & Index",
    desc: "E5-large-v2 vectors + BM25 sparse index + concept-to-chunk mapping. CUDA/MPS/CPU auto-detected.",
    color: "border-amber-500/50 bg-amber-500/5",
    dot: "bg-amber-400",
  },
  {
    name: "Store",
    desc: "JSON file hierarchy with versioning, content-hash dedup, and checkpoint/resume.",
    color: "border-sky-500/50 bg-sky-500/5",
    dot: "bg-sky-400",
  },
];

function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24 sm:py-32 bg-zinc-900/30">
      <div className="max-w-4xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            How it works
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            A six-stage pipeline transforms raw documents into queryable
            knowledge stores with hybrid search.
          </p>
        </div>

        <div className="relative">
          {/* Connecting line */}
          <div className="absolute left-[19px] top-4 bottom-4 w-px bg-gradient-to-b from-amber-500/40 via-violet-500/40 to-sky-500/40 hidden sm:block" />

          <div className="space-y-6 reveal-stagger">
            {PIPELINE_STAGES.map((stage, i) => (
              <div key={stage.name} className="flex gap-5 items-start group">
                <div className="relative flex-shrink-0 mt-1.5 hidden sm:block">
                  <div
                    className={`w-[10px] h-[10px] rounded-full ${stage.dot} ring-4 ring-zinc-950`}
                  />
                </div>
                <div
                  className={`flex-1 rounded-xl border p-5 ${stage.color} transition-colors`}
                >
                  <div className="flex items-center gap-3 mb-1.5">
                    <span className="text-xs font-mono text-zinc-500">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <h3 className="font-semibold text-zinc-100">
                      {stage.name}
                    </h3>
                  </div>
                  <p className="text-sm text-zinc-400 leading-relaxed">
                    {stage.desc}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

const COMPARISON_FEATURES = [
  {
    feature: "Hierarchical chunking (L0\u2013L3)",
    ingestible: true,
    langchain: "Flat only",
    llamaindex: "Flat only",
    unstructured: "Flat only",
  },
  {
    feature: "Built-in hybrid search",
    ingestible: "Vector + BM25 + Concept",
    langchain: "Requires separate setup",
    llamaindex: "Requires separate setup",
    unstructured: false,
  },
  {
    feature: "Token-efficient retrieval",
    ingestible: "88\u201399% reduction",
    langchain: "Depends on setup",
    llamaindex: "Depends on setup",
    unstructured: false,
  },
  {
    feature: "LLM enrichment",
    ingestible: "Summaries, concepts, questions, KG",
    langchain: "Manual",
    llamaindex: "Manual",
    unstructured: false,
  },
  {
    feature: "25+ format parsers",
    ingestible: true,
    langchain: "Via integrations",
    llamaindex: "Via integrations",
    unstructured: true,
  },
  {
    feature: "Cross-document search",
    ingestible: true,
    langchain: "Manual",
    llamaindex: true,
    unstructured: false,
  },
  {
    feature: "MCP server",
    ingestible: true,
    langchain: false,
    llamaindex: false,
    unstructured: false,
  },
  {
    feature: "REST API",
    ingestible: true,
    langchain: false,
    llamaindex: false,
    unstructured: "Via hosted",
  },
  {
    feature: "Production features",
    ingestible: "Rate limiting, auth, metrics, Docker",
    langchain: "Framework",
    llamaindex: "Framework",
    unstructured: "Via hosted",
  },
  {
    feature: "Knowledge graph",
    ingestible: true,
    langchain: "Manual",
    llamaindex: "Via KG index",
    unstructured: false,
  },
];

function ComparisonCell({ value }: { value: boolean | string }) {
  if (value === true) {
    return (
      <svg className="w-5 h-5 text-emerald-400 mx-auto" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
      </svg>
    );
  }
  if (value === false) {
    return <span className="text-zinc-600">&mdash;</span>;
  }
  return <span>{value}</span>;
}

function ComparisonTable() {
  const competitors = ["langchain", "llamaindex", "unstructured"] as const;
  const competitorLabels: Record<string, string> = {
    langchain: "LangChain",
    llamaindex: "LlamaIndex",
    unstructured: "Unstructured",
  };

  return (
    <section id="compare" className="py-24 sm:py-32">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            How Ingestible Compares
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            A purpose-built ingestion pipeline vs. general-purpose frameworks.
          </p>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 overflow-hidden reveal">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-zinc-800">
                  <th className="text-left text-zinc-400 font-medium px-5 py-4 w-[220px]">
                    Feature
                  </th>
                  <th className="text-center px-4 py-4 bg-amber-500/[0.06] border-x border-amber-500/20">
                    <span className="font-semibold text-amber-400">Ingestible</span>
                  </th>
                  {competitors.map((c) => (
                    <th key={c} className="text-center text-zinc-400 font-medium px-4 py-4">
                      {competitorLabels[c]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COMPARISON_FEATURES.map((row, i) => (
                  <tr
                    key={row.feature}
                    className={`border-b border-zinc-800/60 ${i === COMPARISON_FEATURES.length - 1 ? "border-b-0" : ""}`}
                  >
                    <td className="px-5 py-3.5 text-zinc-300 font-medium">
                      {row.feature}
                    </td>
                    <td className="px-4 py-3.5 text-center text-zinc-200 bg-amber-500/[0.06] border-x border-amber-500/20">
                      <ComparisonCell value={row.ingestible} />
                    </td>
                    {competitors.map((c) => (
                      <td key={c} className="px-4 py-3.5 text-center text-zinc-400">
                        <ComparisonCell value={row[c]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}

function Install() {
  return (
    <section id="install" className="py-24 sm:py-32">
      <div className="max-w-4xl mx-auto px-6">
        <div className="text-center mb-12 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            Start in 30 seconds
          </h2>
          <p className="mt-4 text-zinc-400">
            Install from PyPI or pull the Docker image.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-6 reveal-stagger">
          <CodeCard title="pip">
            {`# Base install (~50MB)
pip install ingestible

# With local embeddings (no API keys)
pip install ingestible[local]

# Ingest a document
ingest add /path/to/doc.pdf -v

# Search
ingest search <doc_id> "your query"`}
          </CodeCard>

          <CodeCard title="Docker">
            {`# Pull and run
docker run -d \\
  -p 8081:8081 \\
  -v ingestible-data:/app/data \\
  ghcr.io/simplyliz/ingestible:latest

# API + Web UI at localhost:8081
# Health check: /health/ready
# Metrics: /metrics`}
          </CodeCard>
        </div>

        <div className="mt-8 text-center">
          <div className="inline-flex flex-wrap justify-center gap-3">
            <Badge>Python 3.11&ndash;3.13</Badge>
            <Badge>ChromaDB / pgvector / Qdrant</Badge>
            <Badge>Anthropic / OpenAI / Gemini / Ollama</Badge>
            <Badge>MCP / REST API / CLI</Badge>
          </div>
        </div>
      </div>
    </section>
  );
}

function CodeCard({
  title,
  children,
}: {
  title: string;
  children: string;
}) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-zinc-800 bg-zinc-900/80">
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
          <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
          <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
        </div>
        <span className="text-xs font-medium text-zinc-500 ml-2">{title}</span>
      </div>
      <pre className="p-5 text-sm font-mono text-zinc-300 leading-relaxed overflow-x-auto">
        <code>{children}</code>
      </pre>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-xs font-medium px-3 py-1.5 rounded-full border border-zinc-800 text-zinc-400">
      {children}
    </span>
  );
}

function Examples() {
  return (
    <section id="examples" className="py-24 sm:py-32 bg-zinc-900/30">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-12 reveal">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
            See it in action
          </h2>
          <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
            Three ways to integrate — pick what fits your stack.
          </p>
        </div>

        <div className="grid sm:grid-cols-1 lg:grid-cols-3 gap-6 reveal-stagger">
          <CodeCard title="Python API">
            {`from ingestible import Ingestible

ing = Ingestible()

# Ingest a document
doc = ing.ingest("/path/to/report.pdf")
print(f"Ingested: {doc.title} ({doc.total_chunks} chunks)")

# Search
results = ing.search(doc.doc_id, "quarterly revenue")
for r in results:
    print(f"[{r.score:.2f}] {r.content[:100]}...")`}
          </CodeCard>

          <CodeCard title="REST API">
            {`# Ingest a file
curl -X POST http://localhost:8081/ingest \\
  -F "file=@report.pdf"

# Search
curl http://localhost:8081/documents/report/search \\
  -d '{"query": "quarterly revenue", "top_k": 5}'

# Response
# {"results": [{"chunk_id": "l3_042", "score": 0.94,
#   "content": "Q3 revenue grew 23% YoY to..."}]}`}
          </CodeCard>

          <CodeCard title="MCP (AI Agents)">
            {`// Claude/GPT can search via MCP
{
  "tool": "ingestible_search",
  "input": {
    "doc_id": "report",
    "query": "quarterly revenue"
  }
}

// Agent gets structured results
// with chunk hierarchy context`}
          </CodeCard>
        </div>
      </div>
    </section>
  );
}

function CTA() {
  return (
    <section className="py-24 sm:py-32 bg-zinc-900/30">
      <div className="max-w-3xl mx-auto px-6 text-center">
        <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
          Ready to stop burning tokens?
        </h2>
        <p className="mt-4 text-zinc-400 max-w-lg mx-auto">
          Ingestible is open source under the Apache License 2.0.
          Free to use, modify, and self-host, commercially or not.
        </p>
        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
          <a
            href={PYPI_URL}
            className="btn-press w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-xl bg-amber-500 text-zinc-950 font-semibold text-sm hover:bg-amber-400 transition-colors"
          >
            Install from PyPI
            <ArrowRightIcon />
          </a>
          <a
            href={DOCS_URL}
            className="btn-press w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-xl border border-zinc-700 text-zinc-200 font-semibold text-sm hover:border-zinc-500 hover:bg-zinc-900 transition-colors"
          >
            Read the docs
          </a>
        </div>
      </div>
    </section>
  );
}

import { ScrollReveal } from "@/components/scroll-reveal";

export default function Home() {
  return (
    <main>
      <Hero />
      <Features />
      <SupportedFormats />
      <HowItWorks />
      <ComparisonTable />
      <Install />
      <Examples />
      <CTA />
      <ScrollReveal />
    </main>
  );
}

/* ── Icons ── */

function GithubIcon() {
  return (
    <svg
      className="w-4 h-4"
      fill="currentColor"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function ArrowRightIcon({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"
      />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
      />
    </svg>
  );
}

function LayersIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L12 12.75 6.429 9.75m11.142 0l4.179 2.25-9.75 5.25-9.75-5.25 4.179-2.25"
      />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
      />
    </svg>
  );
}

function SparklesIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"
      />
    </svg>
  );
}

function ServerIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M21.75 17.25v-.228a4.5 4.5 0 00-.12-1.03l-2.268-9.64a3.375 3.375 0 00-3.285-2.602H7.923a3.375 3.375 0 00-3.285 2.602l-2.268 9.64a4.5 4.5 0 00-.12 1.03v.228m19.5 0a3 3 0 01-3 3H5.25a3 3 0 01-3-3m19.5 0a3 3 0 00-3-3H5.25a3 3 0 00-3 3m16.5 0h.008v.008h-.008v-.008zm-3 0h.008v.008h-.008v-.008z"
      />
    </svg>
  );
}

function TerminalIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z"
      />
    </svg>
  );
}
