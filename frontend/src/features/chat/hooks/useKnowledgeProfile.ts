import { useState, useEffect } from 'react';
import { KnowledgeProfileUI } from '../../../shared/types/common.types';
import { fetchKnowledgeProfile } from '../api/chatApi';

export function useKnowledgeProfile(): KnowledgeProfileUI | null {
  const [profile, setProfile] = useState<KnowledgeProfileUI | null>(null);

  useEffect(() => {
    let isMounted = true;
    fetchKnowledgeProfile()
      .then((data: KnowledgeProfileUI) => {
        if (isMounted) setProfile(data);
      })
      .catch(() => {
        // Fallback silently if offline or running in mock unit tests
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return profile;
}
