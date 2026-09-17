import { marked } from 'marked';
import DOMPurify from 'dompurify';

// Tùy biến marked renderer cho liên kết ngoài và bảng cuộn ngang an toàn
const renderer = new marked.Renderer();
const renderDefaultTable = renderer.table;

renderer.link = ({ href, title, text }) => {
  const titleAttr = title ? ` title="${title}"` : '';
  return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer" class="chat-markdown-link">${text}</a>`;
};

renderer.table = function (token) {
  const tableHtml = renderDefaultTable.call(this, token).replace(
    '<table>',
    '<table class="chat-markdown-table">'
  );
  return `<div class="table-responsive-wrapper">${tableHtml}</div>`;
};

marked.use({
  renderer,
  gfm: true,
  breaks: true,
});

const cache = new Map<string, string>();
const MAX_CACHE_SIZE = 200;

export function renderMarkdown(rawMarkdown: string): string {
  if (!rawMarkdown) return '';
  if (cache.has(rawMarkdown)) {
    return cache.get(rawMarkdown)!;
  }

  const rawHtml = marked.parse(rawMarkdown) as string;
  const cleanHtml = DOMPurify.sanitize(rawHtml, {
    ADD_ATTR: ['target', 'rel', 'class'],
  });

  if (cache.size >= MAX_CACHE_SIZE) {
    const firstKey = cache.keys().next().value;
    if (firstKey) cache.delete(firstKey);
  }
  cache.set(rawMarkdown, cleanHtml);

  return cleanHtml;
}
