import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { DemoStoreProvider } from "./state/DemoStore";
import { DiscreetSwitcher } from "./components/layout/DiscreetSwitcher";
import { DemoOverlay } from "./components/demo/DemoOverlay";
import "./styles/demoOverlay.css";
import { ChatPage } from "./pages/ChatPage";
import { AgentPage } from "./pages/AgentPage";
import { AgentLivePage } from "./pages/AgentLivePage";
import { AdminPage } from "./pages/AdminPage";
import { AdminSettingsPage } from "./pages/AdminSettingsPage";
import { AdminStatsPage } from "./pages/AdminStatsPage";
import { AdminKnowledgePage } from "./pages/AdminKnowledgePage";
import { AdminUsersPage } from "./pages/AdminUsersPage";

export default function App() {
  return (
    <DemoStoreProvider>
      <HashRouter>
        <div className="demo-shell">
          <DiscreetSwitcher />
          {/* Incrustations de la demonstration : montees une seule fois, au
              dessus de tout, pour survivre aux bascules de page (le carton
              final s'affiche alors que la supervision est encore visible). */}
          <DemoOverlay />
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/agent" element={<AgentPage />} />
            {/* Poste conseiller REEL (file du moteur, prise en charge, reponse
                humaine). /agent reste la scene rejouee de la demonstration. */}
            <Route path="/agent/live" element={<AgentLivePage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/admin/settings" element={<AdminSettingsPage />} />
            <Route path="/admin/statistiques" element={<AdminStatsPage />} />
            <Route path="/admin/base-connaissances" element={<AdminKnowledgePage />} />
            <Route path="/admin/utilisateurs" element={<AdminUsersPage />} />
          </Routes>
        </div>
      </HashRouter>
    </DemoStoreProvider>
  );
}
