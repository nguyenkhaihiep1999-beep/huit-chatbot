import React from 'react';
import { ExternalLink, BookOpen } from 'lucide-react';
import { SourceCitation } from '../../../shared/types/common.types';

interface SourceCitationsProps {
  sources: SourceCitation[];
}

export const SourceCitations: React.FC<SourceCitationsProps> = ({ sources }) => {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="source-citations-bar">
      <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
        <BookOpen size={13} /> Nguồn minh chứng:
      </span>
      {sources.map((s) => (
        <a
          key={s.i}
          href={s.url}
          target="_blank"
          rel="noopener noreferrer"
          className="source-badge"
          title={s.text}
        >
          <span>[{s.i}]</span>
          <span>{s.title.length > 28 ? s.title.substring(0, 28) + '...' : s.title}</span>
          <ExternalLink size={11} />
        </a>
      ))}
    </div>
  );
};
