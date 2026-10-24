import React, { useState } from 'react';
import { ChevronDown, ChevronUp, CheckCircle2, Activity } from 'lucide-react';
import { TraceStep } from '../../../shared/types/common.types';

interface TraceTimelineProps {
  trace?: TraceStep[];
  cached?: boolean;
}

export const TraceTimeline: React.FC<TraceTimelineProps> = ({ trace, cached }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!trace || trace.length === 0) return null;

  return (
    <div className="rag-trace-box" style={{ marginTop: '10px' }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          background: 'none',
          border: 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          width: '100%',
          cursor: 'pointer',
          color: 'var(--text-muted)',
          fontSize: '0.78rem',
          fontWeight: 600,
          padding: '2px 0',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Activity size={13} color="var(--primary)" />
          Tiến trình truy xuất RAG {cached ? '(0ms RAM Cache)' : `(${trace.length} bước)`}
        </span>
        {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {isOpen && (
        <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {trace.map((step) => (
            <div key={step.step} className="trace-step success">
              <CheckCircle2 size={12} />
              <span>
                <strong>{step.name}:</strong> {step.detail}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
