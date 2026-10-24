import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ToastProvider } from '../components/Toast.jsx'
import { Loading } from '../components/states.jsx'
import { ApiContext } from '../hooks/useApi.js'
import AccountPage from '../pages/AccountPage.jsx'
import AdminPage from '../pages/AdminPage.jsx'
import ApprovalsPage from '../pages/ApprovalsPage.jsx'
import FindingPage from '../pages/FindingPage.jsx'
import HomePage from '../pages/HomePage.jsx'
import NotFound from '../pages/NotFound.jsx'
import PlanPage from '../pages/PlanPage.jsx'
import ProjectAnalysisPage from '../pages/ProjectAnalysisPage.jsx'
import AgentRunPage from '../pages/AgentRunPage.jsx'
import ProjectAssistantPage from '../pages/ProjectAssistantPage.jsx'
import ProjectFindingsPage from '../pages/ProjectFindingsPage.jsx'
import AlertPage from '../pages/AlertPage.jsx'
import ProjectAlertsPage from '../pages/ProjectAlertsPage.jsx'
import ProjectProposalsPage from '../pages/ProjectProposalsPage.jsx'
import ProjectGovernancePage from '../pages/ProjectGovernancePage.jsx'
import ProjectLayoutPage from '../pages/ProjectLayoutPage.jsx'
import ProjectOverviewPage from '../pages/ProjectOverviewPage.jsx'
import ProjectPlansPage from '../pages/ProjectPlansPage.jsx'
import ProjectRunsPage from '../pages/ProjectRunsPage.jsx'
import ProjectSetupPage from '../pages/ProjectSetupPage.jsx'
import ProjectsPage from '../pages/ProjectsPage.jsx'
import ResultPage from '../pages/ResultPage.jsx'
import RunReportPage from '../pages/RunReportPage.jsx'
import RequestAccessPage from '../pages/RequestAccessPage.jsx'
import RoadmapPage from '../pages/RoadmapPage.jsx'
import SignInPage from '../pages/SignInPage.jsx'
import { api as defaultApi } from '../services/api.js'
import { ThemeProvider } from '../theme/ThemeContext.jsx'
import { AuthProvider } from './AuthContext.jsx'
import AppShell from './AppShell.jsx'
import RequireAuth from './RequireAuth.jsx'
import RequireRole from './RequireRole.jsx'

// Developer-only component gallery for reviewing every component in every theme. It is
// not part of the production build and is not linked from the navbar.
const DesignSystemPage = import.meta.env.DEV ? lazy(() => import('../pages/DesignSystemPage.jsx')) : null

// The caller supplies the router (BrowserRouter in main.jsx, MemoryRouter in tests).
export default function App({ api = defaultApi }) {
  return (
    <ApiContext.Provider value={api}>
      <ThemeProvider>
        <AuthProvider api={api}>
          <ToastProvider>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<HomePage />} />
                <Route path="signin" element={<SignInPage />} />
                <Route path="request-access" element={<RequestAccessPage />} />
                <Route path="signup" element={<Navigate to="/request-access" replace />} /> {/* no self-registration: accounts are created by an administrator */}
                <Route path="roadmap" element={<RoadmapPage />} />
                {DesignSystemPage && (
                  <Route
                    path="design-system"
                    element={
                      <Suspense fallback={<Loading />}>
                        <DesignSystemPage />
                      </Suspense>
                    }
                  />
                )}
                <Route element={<RequireAuth />}>
                  <Route path="account" element={<AccountPage />} />
                  <Route path="approvals" element={<ApprovalsPage />} />
                  <Route element={<RequireRole roles={['admin', 'super_admin']} what="administration" />}>
                    <Route path="admin" element={<AdminPage />} />
                  </Route>
                  <Route path="projects" element={<ProjectsPage />} />
                  <Route path="projects/:projectId" element={<ProjectLayoutPage />}>
                    <Route index element={<ProjectOverviewPage />} />
                    <Route path="setup" element={<ProjectSetupPage />} />
                    <Route path="analysis" element={<ProjectAnalysisPage />} />
                    <Route path="plans" element={<ProjectPlansPage />} />
                    <Route path="plans/:planId" element={<PlanPage />} />
                    <Route path="runs" element={<ProjectRunsPage />} />
                    <Route path="runs/:runId" element={<RunReportPage />} />
                    <Route path="runs/:runId/results/:resultId" element={<ResultPage />} />
                    <Route path="findings" element={<ProjectFindingsPage />} />
                    <Route path="findings/:findingId" element={<FindingPage />} />
                    <Route path="assistant" element={<ProjectAssistantPage />} />
                    <Route path="assistant/:runId" element={<AgentRunPage />} />
                    <Route path="alerts" element={<ProjectAlertsPage />} />
                    <Route path="alerts/:alertId" element={<AlertPage />} />
                    <Route path="proposals" element={<ProjectProposalsPage />} />
                    <Route path="governance" element={<ProjectGovernancePage />} />
                  </Route>
                </Route>
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </ToastProvider>
        </AuthProvider>
      </ThemeProvider>
    </ApiContext.Provider>
  )
}
