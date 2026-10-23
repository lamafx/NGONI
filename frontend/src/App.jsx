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
import { AdminConversationsPage } from "./pages/AdminConversationsPage";
import { AdminTicketsPage } from "./pages/AdminTicketsPage";
import { AdminDiagnosticsPage } from "./pages/AdminDiagnosticsPage";
import { AdminAgentsPage } from "./pages/AdminAgentsPage";
import { AdminCapabilitiesPage } from "./pages/AdminCapabilitiesPage";
import { LoginPage } from "./pages/LoginPage";
import { RequireRole } from "./components/layout/RequireRole";

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
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/chat" element={<RequireRole roles={["client"]}><ChatPage /></RequireRole>} />
            <Route path="/agent" element={<RequireRole roles={["conseiller", "admin"]}><AgentPage /></RequireRole>} />
            {/* Poste conseiller REEL (file du moteur, prise en charge, reponse
                humaine). /agent reste la scene rejouee de la demonstration. */}
            <Route path="/agent/live" element={<RequireRole roles={["conseiller", "admin"]}><AgentLivePage /></RequireRole>} />
            <Route path="/admin" element={<RequireRole roles={["admin"]}><AdminPage /></RequireRole>} />
            <Route path="/admin/settings" element={<RequireRole roles={["admin"]}><AdminSettingsPage /></RequireRole>} />
            <Route path="/admin/statistiques" element={<RequireRole roles={["admin"]}><AdminStatsPage /></RequireRole>} />
            <Route path="/admin/base-connaissances" element={<RequireRole roles={["admin"]}><AdminKnowledgePage /></RequireRole>} />
            <Route path="/admin/utilisateurs" element={<RequireRole roles={["admin"]}><AdminUsersPage /></RequireRole>} />
            <Route path="/admin/conversations" element={<RequireRole roles={["admin"]}><AdminConversationsPage mode="all" /></RequireRole>} />
            <Route path="/admin/escalades" element={<RequireRole roles={["admin"]}><AdminConversationsPage mode="escalated" /></RequireRole>} />
            <Route path="/admin/demandes" element={<RequireRole roles={["admin"]}><AdminTicketsPage /></RequireRole>} />
            <Route path="/admin/diagnostics" element={<RequireRole roles={["admin"]}><AdminDiagnosticsPage /></RequireRole>} />
            <Route path="/admin/agents" element={<RequireRole roles={["admin"]}><AdminAgentsPage /></RequireRole>} />
            <Route path="/admin/capacites" element={<RequireRole roles={["admin"]}><AdminCapabilitiesPage /></RequireRole>} />
          </Routes>
        </div>
      </HashRouter>
    </DemoStoreProvider>
  );
}
