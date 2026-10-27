import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ThemeContext, type Theme } from "./theme";
import VariantA from "./variants/A";
import VariantB from "./variants/B";
import VariantC from "./variants/C";
import Switcher from "./Switcher";
import "./base.css";

// Throwaway prototype for wayfinder #34: three radically different Search
// Results looks, switchable via ?variant=A|B|C and ?theme=light|dark, plus a
// floating pill. Fake data inline; no backend calls.

function useQuery() {
  const [params, setParams] = useState(
    () => new URLSearchParams(window.location.search)
  );
  useEffect(() => {
    const sync = () => setParams(new URLSearchParams(window.location.search));
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  return params;
}

function App() {
  const q = useQuery();
  const variant = (q.get("variant") ?? "A").toUpperCase();
  const theme: Theme = q.get("theme") === "dark" ? "dark" : "light";
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return (
    <ThemeContext.Provider value={theme}>
      {variant === "A" && <VariantA />}
      {variant === "B" && <VariantB />}
      {variant === "C" && <VariantC />}
      <Switcher />
    </ThemeContext.Provider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
