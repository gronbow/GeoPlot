import { useCallback, useEffect, useMemo, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open } from "@tauri-apps/plugin-dialog";

import { DropZone } from "../components/DropZone";
import { ProjectSidebar } from "../components/ProjectSidebar";
import { ReviewWorkspace } from "../components/ReviewWorkspace";
import { isTauriRuntime, tauriBackend, type DesktopBackend } from "../lib/backend";
import type {
  DesktopReport,
  InspectResult,
  ProjectSummary,
} from "../types/desktop";

interface AppProps {
  backend?: DesktopBackend;
  chooseFile?: () => Promise<string | null>;
}

function titleFromPath(path: string): string {
  const filename = path.split(/[\\/]/).pop() || "New project";
  return filename.replace(/\.[^.]+$/, "").slice(0, 120) || "New project";
}

function caughtMessage(caught: unknown, fallback: string): string {
  if (typeof caught === "string") return caught;
  if (caught instanceof Error && caught.message) return caught.message;
  return fallback;
}

async function defaultChooseFile(): Promise<string | null> {
  const selected = await open({
    multiple: false,
    directory: false,
    filters: [
      {
        name: "GeoPlot data",
        extensions: ["xlsx", "csv", "txt"],
      },
    ],
  });
  return typeof selected === "string" ? selected : null;
}

export function App({ backend = tauriBackend, chooseFile = defaultChooseFile }: AppProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [removedProjects, setRemovedProjects] = useState<ProjectSummary[]>([]);
  const [activeProject, setActiveProject] = useState<ProjectSummary | null>(null);
  const [report, setReport] = useState<DesktopReport<InspectResult> | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runtimeAvailable = useMemo(
    () => backend !== tauriBackend || isTauriRuntime(),
    [backend],
  );

  const refreshProjects = useCallback(async () => {
    if (!runtimeAvailable) return;
    const [localProjects, localRemovedProjects] = await Promise.all([
      backend.listProjects(),
      backend.listRemovedProjects(),
    ]);
    setProjects(localProjects);
    setRemovedProjects(localRemovedProjects);
    setActiveProject((current) =>
      current
        ? localProjects.find((project) => project.id === current.id) ?? current
        : localProjects[0] ?? null,
    );
  }, [backend, runtimeAvailable]);

  useEffect(() => {
    void refreshProjects().catch(() => setError("Local project storage is unavailable."));
  }, [refreshProjects]);

  useEffect(() => {
    if (!runtimeAvailable || !activeProject?.source || report) return;
    let cancelled = false;
    setBusy(true);
    void backend
      .inspectProject(activeProject.id)
      .then((inspected) => {
        if (!cancelled) setReport(inspected);
      })
      .catch((caught) => {
        if (!cancelled) setError(caughtMessage(caught, "The saved local project could not be inspected."));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeProject, backend, report, runtimeAvailable]);

  const importAndInspect = useCallback(
    async (sourcePath: string) => {
      if (!runtimeAvailable || busy) return;
      setBusy(true);
      setError(null);
      try {
        const project =
          activeProject && !activeProject.source
            ? activeProject
            : await backend.createProject(titleFromPath(sourcePath));
        const imported = await backend.importSourceFile(project.id, sourcePath, false);
        const inspected = await backend.inspectProject(project.id);
        setActiveProject(imported.project);
        setReport(inspected);
        await refreshProjects();
      } catch (caught) {
        setError(caughtMessage(caught, "The local import was not completed."));
      } finally {
        setBusy(false);
      }
    }, [activeProject, backend, busy, refreshProjects, runtimeAvailable],
  );

  const chooseAndImport = useCallback(async () => {
    if (!runtimeAvailable) {
      setError("Run the interface in Tauri to choose local files.");
      return;
    }
    const selected = await chooseFile();
    if (selected) await importAndInspect(selected);
  }, [chooseFile, importAndInspect, runtimeAvailable]);

  useEffect(() => {
    if (!isTauriRuntime()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (disposed) return;
        if (event.payload.type === "over") setDragging(true);
        if (event.payload.type === "leave") setDragging(false);
        if (event.payload.type === "drop") {
          setDragging(false);
          const [path] = event.payload.paths;
          if (path) void importAndInspect(path);
        }
      })
      .then((stop) => {
        if (disposed) stop();
        else unlisten = stop;
      });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [importAndInspect]);

  const startNewProject = useCallback(async () => {
    if (!runtimeAvailable) return;
    try {
      const project = await backend.createProject("Untitled project");
      setProjects((current) => [project, ...current]);
      setActiveProject(project);
      setReport(null);
    } catch {
      setError("A new local project could not be created.");
    }
  }, [backend, runtimeAvailable]);

  const renameProject = useCallback(async (project: ProjectSummary, title: string) => {
    setError(null);
    try {
      const updated = await backend.renameProject(project.id, title);
      setProjects((current) => current.map((item) => item.id === updated.id ? updated : item));
      setActiveProject((current) => current?.id === updated.id ? updated : current);
    } catch (caught) {
      setError(caughtMessage(caught, "The local project could not be renamed."));
      throw caught;
    }
  }, [backend]);

  const removeProject = useCallback(async (project: ProjectSummary) => {
    setError(null);
    try {
      const removed = await backend.removeProject(project.id);
      const position = projects.findIndex((item) => item.id === project.id);
      const remaining = projects.filter((item) => item.id !== project.id);
      setProjects(remaining);
      setRemovedProjects((current) => [removed, ...current.filter((item) => item.id !== removed.id)]);
      if (activeProject?.id === project.id) {
        const next = remaining[position] ?? remaining[position - 1] ?? remaining[0] ?? null;
        setActiveProject(next);
        setReport(null);
        setDragging(false);
      }
    } catch (caught) {
      setError(caughtMessage(caught, "The local project could not be removed safely."));
      throw caught;
    }
  }, [activeProject?.id, backend, projects]);

  const restoreProject = useCallback(async (project: ProjectSummary) => {
    setError(null);
    try {
      const restored = await backend.restoreProject(project.id);
      setRemovedProjects((current) => current.filter((item) => item.id !== restored.id));
      setProjects((current) => [restored, ...current.filter((item) => item.id !== restored.id)]);
    } catch (caught) {
      setError(caughtMessage(caught, "The local project could not be restored."));
      throw caught;
    }
  }, [backend]);

  return (
    <div className="app-shell">
      <ProjectSidebar
        projects={projects}
        removedProjects={removedProjects}
        activeProjectId={activeProject?.id ?? null}
        onSelect={(project) => {
          setActiveProject(project);
          setReport(null);
        }}
        onNew={() => void startNewProject()}
        onRename={renameProject}
        onRemove={removeProject}
        onRestore={restoreProject}
      />
      <main className="main-surface">
        {error && (
          <div className="error-banner" role="alert">
            <strong>Local workflow stopped.</strong> {error}
          </div>
        )}
        {report && activeProject ? (
          <ReviewWorkspace
            key={`${activeProject.id}-${report.result.source.sha256}-${String(report.result.source.selected_sheet)}-${activeProject.selected_layout}`}
            backend={backend}
            project={activeProject}
            report={report}
            onImportAnother={() => void chooseAndImport()}
            onProjectUpdate={(updated) => {
              setActiveProject(updated);
              setProjects((current) =>
                current.map((project) => (project.id === updated.id ? updated : project)),
              );
            }}
            onInspectionUpdate={setReport}
            onError={(message) => setError(message || null)}
          />
        ) : (
          <DropZone
            isBusy={busy}
            isDragging={dragging}
            onChoose={() => void chooseAndImport()}
          />
        )}
      </main>
    </div>
  );
}
