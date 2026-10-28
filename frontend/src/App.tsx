import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AdhocSearchPage from "./pages/AdhocSearchPage";
import BargainsPage from "./pages/BargainsPage";
import ChatSurface from "./pages/ChatSurface";
import SearchResultsPage from "./pages/SearchResultsPage";
import SessionsPage from "./pages/SessionsPage";
import Tray from "./components/Tray";
import { applyTheme, initialTheme, toggleTheme, type Theme } from "./theme";
import { loadViewed, markViewed, type ViewedMap } from "./unread";

applyTheme(initialTheme());

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => initialTheme());
  const [viewed, setViewed] = useState<ViewedMap>(() => loadViewed());

  const onViewed = (sessionId: number | string) => {
    setViewed(markViewed(viewed, sessionId));
  };

  const onToggleTheme = () => setTheme(toggleTheme(theme));

  return (
    <div className="app-shell">
      <Tray theme={theme} onToggleTheme={onToggleTheme} viewed={viewed} />
      <main className="page-content" style={{ flex: 1, minWidth: 0, height: "100%" }}>
        <Routes>
          <Route path="/" element={<ChatSurface viewed={viewed} onViewed={onViewed} />} />
          <Route path="/chat/:id" element={<ChatSurface viewed={viewed} onViewed={onViewed} />} />
          <Route path="/chat/sessions" element={<SessionsPage />} />
          <Route path="/bargains" element={<BargainsPage />} />
          <Route path="/bargains/:id" element={<SearchResultsPage />} />
          <Route path="/search" element={<AdhocSearchPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
