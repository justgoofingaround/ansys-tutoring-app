import { useEffect } from "react";
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  RouterProvider,
  useNavigate,
} from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { RequireRole } from "@/auth/RequireRole";
import { StudentLayout } from "@/layouts/StudentLayout";
import { InstructorLayout } from "@/layouts/InstructorLayout";
import { LoginPage } from "@/pages/login/LoginPage";
import { DashboardPage } from "@/pages/student/DashboardPage";
import { TutorialDetailPage } from "@/pages/student/TutorialDetailPage";
import { RunPage } from "@/pages/student/RunPage";
import { QuizPage } from "@/pages/student/QuizPage";
import { ChatPage } from "@/pages/student/ChatPage";
import { ClassDashboardPage } from "@/pages/instructor/ClassDashboardPage";
import { Placeholder } from "@/pages/Placeholder";

function SessionExpiryListener({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  useEffect(() => {
    const handler = () => {
      qc.setQueryData(["me"], null);
      navigate("/login?expired=1");
    };
    window.addEventListener("session-expired", handler);
    return () => window.removeEventListener("session-expired", handler);
  }, [navigate, qc]);
  return <>{children}</>;
}

const router = createBrowserRouter([
  {
    element: (
      <SessionExpiryListener>
        <RouterOutlet />
      </SessionExpiryListener>
    ),
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        element: (
          <RequireRole role="student">
            <StudentLayout />
          </RequireRole>
        ),
        children: [
          { path: "/", element: <Navigate to="/dashboard" replace /> },
          { path: "/dashboard", element: <DashboardPage /> },
          { path: "/tutorials/:tutorialId", element: <TutorialDetailPage /> },
          { path: "/tutorials/:tutorialId/run", element: <RunPage /> },
          { path: "/tutorials/:tutorialId/quiz", element: <QuizPage /> },
          { path: "/chat", element: <ChatPage /> },
        ],
      },
      {
        element: (
          <RequireRole role="instructor">
            <InstructorLayout />
          </RequireRole>
        ),
        children: [
          { path: "/instructor", element: <Navigate to="/instructor/class" replace /> },
          { path: "/instructor/class", element: <ClassDashboardPage /> },
          { path: "/instructor/tutorials", element: <Placeholder title="Tutorial library" milestone="milestone 5" /> },
          { path: "/instructor/quizzes", element: <Placeholder title="Quizzes" milestone="milestone 6" /> },
          { path: "/instructor/faqs", element: <Placeholder title="FAQ review" milestone="milestone 6" /> },
        ],
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

function RouterOutlet() {
  return <Outlet />;
}

export function App() {
  return <RouterProvider router={router} />;
}
