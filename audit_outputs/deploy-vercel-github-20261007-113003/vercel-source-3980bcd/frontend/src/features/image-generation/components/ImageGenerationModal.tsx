import React, { useState } from 'react';
import { X, Sparkles, Image as ImageIcon, Loader2 } from 'lucide-react';
import { useImageGeneration } from '../hooks/useImageGeneration';

interface ImageGenerationModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ImageGenerationModal: React.FC<ImageGenerationModalProps> = ({ isOpen, onClose }) => {
  const [prompt, setPrompt] = useState('Robot mascot HUIT tại khuôn viên trường đại học phong cách 3D dễ thương');
  const [backend, setBackend] = useState<'flux' | 'svg'>('flux');
  const { loading, result, error, generateImage } = useImageGeneration();

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || loading) return;
    generateImage(prompt.trim(), backend);
  };

  return (
    <div className="lightbox-overlay" onClick={onClose}>
      <div className="lightbox-content" style={{ maxWidth: '640px' }} onClick={(e) => e.stopPropagation()}>
        <div className="lightbox-topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700 }}>
            <Sparkles size={18} color="var(--primary)" />
            <span>Sinh hình ảnh AI HUIT (FLUX.1 / SVG)</span>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            <X size={20} />
          </button>
        </div>

        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px', display: 'block' }}>
                Mô tả hình ảnh (Prompt tiếng Việt hoặc tiếng Anh):
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-input)',
                  color: 'var(--text-main)',
                  fontFamily: 'inherit',
                  fontSize: '0.9rem',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
              <label style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="backend"
                  checked={backend === 'flux'}
                  onChange={() => setBackend('flux')}
                />
                FLUX.1 Photorealistic
              </label>
              <label style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="backend"
                  checked={backend === 'svg'}
                  onChange={() => setBackend('svg')}
                />
                Vector SVG Scene
              </label>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="new-chat-btn"
              style={{ margin: 0, justifyContent: 'center' }}
            >
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> Đang tạo ảnh...
                </>
              ) : (
                <>
                  <ImageIcon size={16} /> Tạo ảnh ngay
                </>
              )}
            </button>
          </form>

          {error && (
            <div style={{ color: 'var(--danger)', fontSize: '0.85rem', padding: '10px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '6px' }}>
              {error}
            </div>
          )}

          {result && (
            <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
              {result.image_url ? (
                <>
                  <img
                    src={result.thumbnail_url || result.image_url}
                    alt="Generated"
                    style={{ maxWidth: '100%', maxHeight: '360px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', objectFit: 'contain' }}
                  />
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <a
                      href={result.image_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="visual-action-btn"
                      style={{ textDecoration: 'none', padding: '6px 12px', fontSize: '0.85rem' }}
                    >
                      <Sparkles size={14} /> Xem ảnh gốc
                    </a>
                    <a
                      href={result.image_url}
                      download={`huit-ai-${result.image_id}.jpg`}
                      className="visual-action-btn"
                      style={{ textDecoration: 'none', padding: '6px 12px', fontSize: '0.85rem' }}
                    >
                      Tải về
                    </a>
                  </div>
                  {result.cached && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      ⚡ Tái sử dụng từ bộ nhớ đệm (Deduplicated)
                    </span>
                  )}
                </>
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Đã tạo ảnh thành công.</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
