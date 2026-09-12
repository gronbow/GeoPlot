interface DropZoneProps {
  isBusy: boolean;
  isDragging: boolean;
  onChoose: () => void;
}

export function DropZone({ isBusy, isDragging, onChoose }: DropZoneProps) {
  return (
    <section
      className={isDragging ? "drop-zone drop-zone-active" : "drop-zone"}
      aria-labelledby="drop-heading"
      aria-busy={isBusy}
    >
      <div className="drop-icon" aria-hidden="true">
        ⇩
      </div>
      <p className="eyebrow">LOCAL DATA WORKSPACE</p>
      <h1 id="drop-heading">
        {isBusy ? "Inspecting your local copy…" : "Drop geochemical data here"}
      </h1>
      <p className="drop-copy">
        GeoPlot copies the selected file into private app storage before
        inspection. Your original stays unchanged.
      </p>
      <button
        className="primary-button"
        type="button"
        aria-busy={isBusy}
        data-busy={isBusy}
        disabled={isBusy}
        onClick={onChoose}
      >
        Choose a file
      </button>
      <p className="file-types">XLSX · CSV · TXT · maximum 20 MiB</p>
    </section>
  );
}
