import { useState, type FormEvent, type MouseEvent } from "react";

import geoplotIcon from "../assets/geoplot-icon-master.png";
import type { ProjectSummary } from "../types/desktop";

interface ProjectSidebarProps {
  projects: ProjectSummary[];
  removedProjects: ProjectSummary[];
  activeProjectId: string | null;
  onSelect: (project: ProjectSummary) => void;
  onNew: () => void;
  onRename: (project: ProjectSummary, title: string) => Promise<void>;
  onRemove: (project: ProjectSummary) => Promise<void>;
  onRestore: (project: ProjectSummary) => Promise<void>;
}

export function ProjectSidebar({
  projects,
  removedProjects,
  activeProjectId,
  onSelect,
  onNew,
  onRename,
  onRemove,
  onRestore,
}: ProjectSidebarProps) {
  const [openActions, setOpenActions] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<ProjectSummary | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [confirmingRemove, setConfirmingRemove] = useState<ProjectSummary | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const stop = (event: MouseEvent) => event.stopPropagation();

  const beginRename = (event: MouseEvent, project: ProjectSummary) => {
    stop(event);
    setOpenActions(null);
    setRenaming(project);
    setRenameTitle(project.title);
  };

  const submitRename = async (event: FormEvent) => {
    event.preventDefault();
    if (!renaming || pendingId) return;
    setPendingId(renaming.id);
    try {
      await onRename(renaming, renameTitle);
      setRenaming(null);
    } catch {
      // The app-level error banner keeps the reason visible while editing stays open.
    } finally {
      setPendingId(null);
    }
  };

  const confirmRemove = async () => {
    if (!confirmingRemove || pendingId) return;
    setPendingId(confirmingRemove.id);
    try {
      await onRemove(confirmingRemove);
      setConfirmingRemove(null);
    } catch {
      // The app-level error banner reports the safe store failure.
    } finally {
      setPendingId(null);
    }
  };

  const restore = async (project: ProjectSummary) => {
    if (pendingId) return;
    setPendingId(project.id);
    try {
      await onRestore(project);
    } catch {
      // The app-level error banner reports the safe store failure.
    } finally {
      setPendingId(null);
    }
  };

  return (
    <aside className="sidebar" aria-label="Projects">
      <div className="brand-row">
        <img className="brand-mark" src={geoplotIcon} alt="" aria-hidden="true" />
        <div><strong>GeoPlot</strong><span>Local geochemistry</span></div>
      </div>
      <div className="sidebar-heading">
        <span>Projects</span>
        <span className="project-count">{projects.length}</span>
      </div>
      <nav className="project-list" aria-label="Local projects">
        {projects.length === 0 ? (
          <p className="empty-list">No local projects yet</p>
        ) : (
          projects.map((project) => (
            <div className="project-row" key={project.id}>
              <button
                className={project.id === activeProjectId ? "project-item project-item-active" : "project-item"}
                type="button"
                onClick={() => onSelect(project)}
              >
                <span title={project.title}>{project.title}</span>
                <small>{project.source ? "Data imported" : "Empty project"}</small>
              </button>
              <button
                className="project-actions"
                type="button"
                aria-label={`Actions for ${project.title}`}
                aria-expanded={openActions === project.id}
                onClick={(event) => {
                  stop(event);
                  setOpenActions((current) => current === project.id ? null : project.id);
                }}
              >
                ⋯
              </button>
              {openActions === project.id && (
                <div className="project-menu" role="menu" aria-label={`Project actions for ${project.title}`}>
                  <button type="button" role="menuitem" onClick={(event) => beginRename(event, project)}>Rename</button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={(event) => {
                      stop(event);
                      setOpenActions(null);
                      setConfirmingRemove(project);
                    }}
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </nav>

      {renaming && (
        <form className="project-inline-panel" aria-label={`Rename ${renaming.title}`} onSubmit={(event) => void submitRename(event)}>
          <label htmlFor="rename-project-title">Project name</label>
          <input
            id="rename-project-title"
            aria-label="Rename project title"
            autoFocus
            maxLength={120}
            value={renameTitle}
            onChange={(event) => setRenameTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setRenaming(null);
            }}
          />
          <div className="project-inline-actions">
            <button type="submit" disabled={pendingId === renaming.id}>Save</button>
            <button type="button" disabled={pendingId === renaming.id} onClick={() => setRenaming(null)}>Cancel</button>
          </div>
        </form>
      )}

      {confirmingRemove && (
        <section className="project-inline-panel remove-confirmation" role="dialog" aria-label={`Remove ${confirmingRemove.title}`}>
          <strong>Remove “{confirmingRemove.title}”?</strong>
          <p>The app-managed project copy, recipe, plan, and outputs will leave the active list. The original external imported file is not touched. You can restore this project later.</p>
          <div className="project-inline-actions">
            <button type="button" disabled={pendingId === confirmingRemove.id} onClick={() => void confirmRemove()}>Remove project</button>
            <button type="button" disabled={pendingId === confirmingRemove.id} onClick={() => setConfirmingRemove(null)}>Cancel</button>
          </div>
        </section>
      )}

      <button className="new-project" type="button" onClick={onNew}>
        <span aria-hidden="true">＋</span> New project
      </button>

      <details className="removed-projects">
        <summary>Recently removed <span>{removedProjects.length}</span></summary>
        {removedProjects.length === 0 ? (
          <p>No removed projects</p>
        ) : (
          <ul>
            {removedProjects.map((project) => (
              <li key={project.id}>
                <span>{project.title}</span>
                <button type="button" disabled={pendingId === project.id} onClick={() => void restore(project)}>Restore</button>
              </li>
            ))}
          </ul>
        )}
      </details>

      <div className="privacy-note">
        <span className="privacy-dot" aria-hidden="true" />
        Local processing only
      </div>
    </aside>
  );
}
