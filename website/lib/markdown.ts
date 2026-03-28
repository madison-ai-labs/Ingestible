import { remark } from "remark";
import html from "remark-html";
import remarkGfm from "remark-gfm";

export async function markdownToHtml(markdown: string): Promise<string> {
  const result = await remark()
    .use(remarkGfm)
    .use(html, { sanitize: false })
    .process(markdown);

  // Add IDs to headings for TOC linking
  let htmlContent = result.toString();
  htmlContent = htmlContent.replace(
    /<h([2-4])>([^<]+)<\/h\1>/g,
    (_, level, text) => {
      const id = text
        .toLowerCase()
        .replace(/[^\w\s-]/g, "")
        .replace(/\s+/g, "-");
      return `<h${level} id="${id}">${text}</h${level}>`;
    }
  );

  return htmlContent;
}
