import Link from "next/link";

const GITHUB_URL = "https://github.com/SimplyLiz/Ingestible";
const PYPI_URL = "https://pypi.org/project/ingestible";

export function Footer() {
  return (
    <footer className="border-t border-zinc-800/60 bg-zinc-950 py-12">
      <div className="max-w-6xl mx-auto px-6">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-8 mb-10">
          <div>
            <h4 className="text-sm font-semibold text-zinc-200 mb-3">
              Documentation
            </h4>
            <ul className="space-y-2">
              <FooterLink href="/docs/Introduction">Getting Started</FooterLink>
              <FooterLink href="/docs/Usage">Usage Guide</FooterLink>
              <FooterLink href="/docs/API-Reference">REST API</FooterLink>
              <FooterLink href="/docs/MCP-Server">MCP Server</FooterLink>
              <FooterLink href="/docs/Deployment">Deployment</FooterLink>
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-zinc-200 mb-3">
              Learn
            </h4>
            <ul className="space-y-2">
              <FooterLink href="/docs/How-It-Works">How It Works</FooterLink>
              <FooterLink href="/docs/Architecture">Architecture</FooterLink>
              <FooterLink href="/docs/Search">How Search Works</FooterLink>
              <FooterLink href="/docs/Token-Economics">Token Economics</FooterLink>
              <FooterLink href="/docs/Features">Features</FooterLink>
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-zinc-200 mb-3">
              Product
            </h4>
            <ul className="space-y-2">
              <FooterLink href="/pricing">Pricing</FooterLink>
              <FooterLink href="/pricing#enterprise">Enterprise</FooterLink>
              <FooterLink href="/security">Security &amp; Privacy</FooterLink>
              <FooterLink href="/#features">Features</FooterLink>
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-zinc-200 mb-3">
              Install
            </h4>
            <ul className="space-y-2">
              <FooterLink href={PYPI_URL}>PyPI</FooterLink>
              <FooterLink href={`${GITHUB_URL}/pkgs/container/ingestible`}>
                Docker
              </FooterLink>
              <FooterLink href="/docs/Changelog">Changelog</FooterLink>
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-zinc-200 mb-3">
              Community
            </h4>
            <ul className="space-y-2">
              <FooterLink href={GITHUB_URL}>GitHub</FooterLink>
              <FooterLink href={`${GITHUB_URL}/issues`}>Issues</FooterLink>
              <FooterLink href={`${GITHUB_URL}/discussions`}>
                Discussions
              </FooterLink>
            </ul>
          </div>
        </div>
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-8 border-t border-zinc-800/60">
          <span className="text-xs text-zinc-600">
            &copy; {new Date().getFullYear()} Ingestible &mdash; PolyForm Small
            Business 1.0.0
          </span>
          <div className="flex items-center gap-6">
            <a
              href={GITHUB_URL}
              className="text-xs text-zinc-600 hover:text-zinc-300 transition-colors"
            >
              GitHub
            </a>
            <a
              href={PYPI_URL}
              className="text-xs text-zinc-600 hover:text-zinc-300 transition-colors"
            >
              PyPI
            </a>
            <a
              href={`${GITHUB_URL}/pkgs/container/ingestible`}
              className="text-xs text-zinc-600 hover:text-zinc-300 transition-colors"
            >
              Docker
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}

function FooterLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const isExternal = href.startsWith("http");
  if (isExternal) {
    return (
      <li>
        <a
          href={href}
          className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          {children}
        </a>
      </li>
    );
  }
  return (
    <li>
      <Link
        href={href}
        className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
      >
        {children}
      </Link>
    </li>
  );
}
