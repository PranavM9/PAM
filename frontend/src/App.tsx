import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import AgentsPage from './pages/AgentsPage'
import ChatPage from './pages/ChatPage'
import GraphPage from './pages/GraphPage'
import GuidesPage from './pages/GuidesPage'
import HomePage from './pages/HomePage'
import ImportPage from './pages/ImportPage'
import SearchPage from './pages/SearchPage'
import VaultPage from './pages/VaultPage'

/** Route table: the home page plus the seven pages of SPEC §3.2. */
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="vault" element={<VaultPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="guides" element={<GuidesPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
