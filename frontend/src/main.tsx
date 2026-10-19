import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { SignInScreen } from "./components/Login";
import { ApiError } from "./lib/api";
import { Card, Empty, Skeleton } from "./components/ui";
import { LiveProvider } from "./lib/live";
import { ThemeProvider } from "./lib/theme";
import { useMeta } from "./lib/queries";
import { useEffect } from "react";
import Overview from "./pages/Overview";

const Signals = lazy(() => import("./pages/Signals"));
const SignalDetail = lazy(() => import("./pages/SignalDetail"));
const Performance = lazy(() => import("./pages/Performance"));
const Strategies = lazy(() => import("./pages/Strategies"));
const CalculatorPage = lazy(() => import("./pages/CalculatorPage"));
const Admin = lazy(() => import("./pages/Admin"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && (e.status === 401 || e.status === 403)) && n < 1,
    },
  },
});

/** Private site: nothing renders (and no live connection opens) until the admin session is valid.
 *  The overview metadata answers 401 without it; a session that expires falls back here too. */
function Gate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meta = useMeta();
  if (meta.error instanceof ApiError && meta.error.status === 401) return <SignInScreen onSignedIn={() => qc.invalidateQueries()} />;
  if (meta.isPending) return <div className="min-h-screen bg-bg" />;
  return <>{children}</>;
}

function Title() {
  const { data } = useMeta();
  useEffect(() => {
    if (data?.app_name) document.title = data.app_name;
  }, [data?.app_name]);
  return null;
}

function NotFound() {
  return (
    <Card>
      <Empty title="Page not found">
        <Link className="link" to="/">Back to the overview</Link>
      </Empty>
    </Card>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <Gate>
          <LiveProvider>
            <BrowserRouter>
              <Title />
              <Layout>
                <Suspense fallback={<Skeleton className="h-96" />}>
                  <Routes>
                    <Route path="/" element={<Overview />} />
                    <Route path="/signals" element={<Signals />} />
                    <Route path="/signals/:id" element={<SignalDetail />} />
                    <Route path="/performance" element={<Performance />} />
                    <Route path="/strategies" element={<Strategies />} />
                    <Route path="/calculator" element={<CalculatorPage />} />
                    <Route path="/admin" element={<Admin />} />
                    <Route path="*" element={<NotFound />} />
                  </Routes>
                </Suspense>
              </Layout>
            </BrowserRouter>
          </LiveProvider>
        </Gate>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
