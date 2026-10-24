import { useState, useEffect } from 'react';
import { KnowledgeProfileUI } from '../../../shared/types/common.types';
import { fetchKnowledgeProfile } from '../api/chatApi';

export const DEFAULT_ILT_PROFILE: KnowledgeProfileUI = {
  profile_id: 'ilt',
  name: 'Innovative Lighting Technologies',
  bot_title: 'Innovative Lighting AI',
  bot_subtitle: 'Đèn trang trí & chiếu sáng cao cấp · Nhà máy Đồng Nai',
  eyebrow: 'Dữ liệu Catalogue ILT 2026',
  empty_title: 'Chiếu sáng kiến trúc. Chuẩn mực quốc tế.',
  empty_description:
    'Tra cứu thông số kỹ thuật đèn bàn, đèn sàn, đèn thả, đèn chùm, năng lực OEM/ODM và tiêu chuẩn xuất khẩu từ Innovative Lighting Technologies.',
  official_contact:
    'Innovative Lighting Technologies: Đường 1, KCN Long Thành, Huyện Long Thành, Đồng Nai, Việt Nam - Hotline: (+84) 251 3514 366 - Email: info@innovativelightingco.com - Website: https://innovativelightingco.com/',
  default_source_url: 'https://innovativelightingco.com/',
  suggestions: [
    { text: 'Danh mục các dòng sản phẩm đèn của ILT?', badge: 'Sản phẩm ILT' },
    { text: 'Thông số kỹ thuật dòng đèn ARNO hoặc BORA?', badge: 'Thông số kỹ thuật' },
    { text: 'Năng lực sản xuất và tiêu chuẩn xuất khẩu tại Đồng Nai?', badge: 'Nhà máy & Chứng nhận' },
    { text: 'Quy trình đặt hàng gia công tùy chỉnh OEM/ODM?', badge: 'Dịch vụ OEM/ODM' },
  ],
};

export function useKnowledgeProfile(): KnowledgeProfileUI {
  const [profile, setProfile] = useState<KnowledgeProfileUI>(DEFAULT_ILT_PROFILE);

  useEffect(() => {
    let isMounted = true;
    fetchKnowledgeProfile()
      .then((data: KnowledgeProfileUI) => {
        if (isMounted && data) setProfile(data);
      })
      .catch(() => {
        // Fallback to DEFAULT_ILT_PROFILE if offline or running in mock unit tests
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return profile;
}
