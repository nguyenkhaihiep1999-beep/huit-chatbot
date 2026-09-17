import React, { useState, useEffect } from 'react';
import { useTheme } from '../features/theme/hooks/useTheme';
import { useChatHistory } from '../features/history/hooks/useChatHistory';
import { useVisualLightbox } from '../features/admission-visuals/hooks/useVisualLightbox';
import { Header } from '../shared/components/Header';
import { HistoryDrawer } from '../features/history/components/HistoryDrawer';
import { ChatWindow } from '../features/chat/components/ChatWindow';
import { VisualLightbox } from '../features/admission-visuals/components/VisualLightbox';
import { ImageGenerationModal } from '../features/image-generation/components/ImageGenerationModal';
import { ConversationSession, ChatMessage } from '../shared/types/common.types';
import { generateUniqueId } from '../shared/utils/idGenerator';
import { useSessionBootstrap } from '../features/session/hooks/useSessionBootstrap';
import { AdminPage } from '../features/admin/components/AdminPage';

export const App: React.FC = () => {
  const { theme, toggleTheme } = useTheme();
  const { sessions, saveSession, deleteSession, clearAllSessions } = useChatHistory();
  const { activeVisual, openLightbox, closeLightbox } = useVisualLightbox();
  useSessionBootstrap();

  const [currentPath, setCurrentPath] = useState<string>(() =>
    typeof window !== 'undefined' ? window.location.pathname : '/'
  );

  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 1100 : false
  );
  const [isImageModalOpen, setIsImageModalOpen] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => generateUniqueId('session'));
  const [sessionMessages, setSessionMessages] = useState<ChatMessage[]>([]);
  const [isOnline, setIsOnline] = useState<boolean>(() => (typeof navigator !== 'undefined' ? navigator.onLine : true));

  // Theo dõi trạng thái mạng và lịch sử URL (popstate)
  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    const handlePopState = () => {
      setCurrentPath(window.location.pathname);
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('popstate', handlePopState);
    };
  }, []);

  const navigateTo = (path: string) => {
    if (typeof window !== 'undefined') {
      window.history.pushState({}, '', path);
      setCurrentPath(path);
    }
  };

  const handleSelectSession = (session: ConversationSession) => {
    setCurrentSessionId(session.sessionId);
    setSessionMessages(session.messages);
  };

  const handleNewChat = () => {
    const newId = generateUniqueId('session');
    setCurrentSessionId(newId);
    setSessionMessages([]);
    if (window.innerWidth < 768) setIsDrawerOpen(false);
  };

  const handleClearAllHistory = () => {
    clearAllSessions();
    handleNewChat();
  };

  // Tuyến đường /admin
  if (currentPath === '/admin') {
    return <AdminPage onNavigateChat={() => navigateTo('/')} />;
  }

  return (
    <div className="app-container">
      {/* Sidebar Drawer */}
      <HistoryDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        sessions={sessions}
        activeSessionId={currentSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={deleteSession}
        onClearAllSessions={handleClearAllHistory}
        theme={theme}
        onToggleTheme={toggleTheme}
        isOnline={isOnline}
        onNavigateAdmin={() => navigateTo('/admin')}
      />

      {/* Main Content Area */}
      <main className="main-content">
        <Header
          onToggleDrawer={() => setIsDrawerOpen(!isDrawerOpen)}
          isDrawerOpen={isDrawerOpen}
          theme={theme}
          onToggleTheme={toggleTheme}
          onOpenImageModal={() => setIsImageModalOpen(true)}
          isOnline={isOnline}
          onNavigateAdmin={() => navigateTo('/admin')}
        />

        <ChatWindow
          activeSessionId={currentSessionId}
          initialMessages={sessionMessages}
          onOpenLightbox={openLightbox}
          onSaveSession={saveSession}
        />
      </main>

      {/* Modals */}
      <VisualLightbox visual={activeVisual} onClose={closeLightbox} />
      <ImageGenerationModal
        isOpen={isImageModalOpen}
        onClose={() => setIsImageModalOpen(false)}
      />
    </div>
  );
};

export default App;
