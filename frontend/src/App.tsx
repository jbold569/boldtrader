import { useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import BargainsPage from "./pages/BargainsPage";
import SearchResultsPage from "./pages/SearchResultsPage";
import { applyTheme, initialTheme, toggleTheme, type Theme } from "./theme";

applyTheme(initialTheme());

function Stub({ name }: { name: string }) {
  return (
    <section style={{ padding: "var(--space-4)" }}>
      <h1 style={{ fontSize: "var(--text-xl)", color: "var(--fg)" }}>{name}</h1>
      <p style={{ color: "var(--muted)" }}>stub — built in a later increment</p>
    </section>
  );
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => initialTheme());
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <nav
        style={{
          display: "flex",
          gap: "var(--space-3)",
          padding: "var(--space-2) var(--space-4)",
          borderBottom: "1px solid var(--border)",
          background: "var(--surface)",
        }}
      >
        <Link to="/">Chat</Link>
        <Link to="/chat/sessions">Sessions</Link>
        <Link to="/bargains">Bargains</Link>
        <Link to="/search">Search</Link>
        <button
          onClick={() => setTheme(toggleTheme(theme))}
          aria-label={`switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? "light" : "dark"}
        </button>
      </nav>
      <Routes>
        <Route path="/" element={<Stub name="ChatSurface" />} />
        <Route path="/chat/:id" element={<Stub name="ChatSurface" />} />
        <Route path="/chat/sessions" element={<Stub name="SessionsPage" />} />
        <Route path="/bargains" element={<BargainsPage />} />
        <Route path="/bargains/:id" element={<SearchResultsPage />} />
        <Route path="/search" element={<Stub name="Search" />} />
      </Routes>
    </div>
  );
}
