import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  LoaderCircle,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type * as PdfJs from "pdfjs-dist";
import { fieldLabel } from "../lib/fields";

export function PageViewer({
  documentUrl,
  currentPage,
  totalPages,
  onPageChange,
  reviewBox,
  reviewLabel,
  reviewConfidence,
}: {
  documentUrl: string;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  reviewBox?: number[] | null;
  reviewLabel?: string;
  reviewConfidence?: number;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderTaskRef = useRef<{ cancel: () => void } | undefined>(undefined);
  const [pdf, setPdf] = useState<PdfJs.PDFDocumentProxy>();
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pageSize, setPageSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setPdf(undefined);
    let loadingTask: PdfJs.PDFDocumentLoadingTask | undefined;
    let pdfWorker: Worker | undefined;
    void Promise.all([
      import("pdfjs-dist"),
      import("pdfjs-dist/build/pdf.worker.min.mjs?worker&inline"),
    ])
      .then(([pdfjs, workerModule]) => {
        if (!active) return;
        pdfWorker = new workerModule.default();
        pdfjs.GlobalWorkerOptions.workerPort = pdfWorker;
        loadingTask = pdfjs.getDocument({ url: documentUrl });
        return loadingTask.promise;
      })
      .then((loaded) => {
        if (loaded && active) setPdf(loaded);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Impossibile aprire il PDF");
          setLoading(false);
        }
      });
    return () => {
      active = false;
      renderTaskRef.current?.cancel();
      if (loadingTask) {
        void (async () => {
          try {
            await loadingTask?.destroy();
          } catch {
            // The loading task may already have completed while the viewer unmounts.
          }
        })();
      } else {
        pdfWorker?.terminate();
      }
    };
  }, [documentUrl]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setViewportSize({ width: element.clientWidth, height: element.clientHeight }),
    );
    observer.observe(element);
    setViewportSize({ width: element.clientWidth, height: element.clientHeight });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!pdf || !canvasRef.current || !viewportSize.width || !viewportSize.height) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    renderTaskRef.current?.cancel();
    pdf
      .getPage(Math.min(Math.max(currentPage, 1), pdf.numPages))
      .then((page) => {
        if (cancelled || !canvasRef.current) return;
        const base = page.getViewport({ scale: 1 });
        const fit = Math.min(
          (viewportSize.width - 44) / base.width,
          (viewportSize.height - 44) / base.height,
        );
        const viewport = page.getViewport({ scale: Math.max(0.1, fit) * (zoom / 100) });
        const canvas = canvasRef.current;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas non disponibile");
        const pixelRatio = window.devicePixelRatio || 1;
        canvas.width = Math.ceil(viewport.width * pixelRatio);
        canvas.height = Math.ceil(viewport.height * pixelRatio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        setPageSize({ width: viewport.width, height: viewport.height });
        const renderTask = page.render({
          canvas,
          canvasContext: context,
          viewport,
          transform:
            pixelRatio === 1 ? undefined : ([pixelRatio, 0, 0, pixelRatio, 0, 0] as [
                number,
                number,
                number,
                number,
                number,
                number,
              ]),
        });
        renderTaskRef.current = renderTask;
        return renderTask.promise.then(() => {
          if (!cancelled) setLoading(false);
        });
      })
      .catch((reason: unknown) => {
        if (!cancelled && !(reason instanceof Error && reason.name === "RenderingCancelledException")) {
          setError(reason instanceof Error ? reason.message : "Errore durante il rendering della pagina");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [pdf, currentPage, zoom, viewportSize]);

  const validBox =
    reviewBox?.length === 4 && reviewBox.every((coordinate) => Number.isFinite(coordinate));
  const bboxColor = reviewLabel?.toLowerCase().includes("data") ? "#f0883e" : "#5b8cff";

  return (
    <div className="simple-pdf-viewer" id="page-viewer">
      <div className="simple-viewer-toolbar">
        <div className="simple-page-controls">
          <button
            onClick={() => onPageChange(Math.max(1, currentPage - 1))}
            disabled={currentPage <= 1}
            aria-label="Pagina precedente"
            title="Pagina precedente"
          >
            <ChevronLeft size={17} />
          </button>
          <span>
            <b>{currentPage}</b> / {pdf?.numPages ?? totalPages}
          </span>
          <button
            onClick={() => onPageChange(Math.min(pdf?.numPages ?? totalPages, currentPage + 1))}
            disabled={currentPage >= (pdf?.numPages ?? totalPages)}
            aria-label="Pagina successiva"
            title="Pagina successiva"
          >
            <ChevronRight size={17} />
          </button>
        </div>
        <div className="simple-zoom-controls">
          <button
            onClick={() => setZoom((value) => Math.max(50, value - 10))}
            disabled={zoom <= 50}
            aria-label="Riduci zoom"
            title="Riduci zoom"
          >
            <ZoomOut size={16} />
          </button>
          <span>{zoom === 100 ? "Adatta" : `${zoom}%`}</span>
          <button
            onClick={() => setZoom((value) => Math.min(200, value + 10))}
            disabled={zoom >= 200}
            aria-label="Aumenta zoom"
            title="Aumenta zoom"
          >
            <ZoomIn size={16} />
          </button>
          <button className="fit-page-button" onClick={() => setZoom(100)}>
            Adatta
          </button>
        </div>
      </div>
      <div className="simple-document-scroll" ref={scrollRef}>
        <div
          className="simple-page-frame"
          style={{ width: pageSize.width || "auto", height: pageSize.height || "auto" }}
        >
          <canvas ref={canvasRef} aria-label={`Pagina ${currentPage} del PDF`} />
          {validBox && (
            <>
              <span
                className="review-bounding-box"
                style={{
                  "--bbox-color": bboxColor,
                  left: `${reviewBox[0] * 100}%`,
                  top: `${reviewBox[1] * 100}%`,
                  width: `${(reviewBox[2] - reviewBox[0]) * 100}%`,
                  height: `${(reviewBox[3] - reviewBox[1]) * 100}%`,
                } as CSSProperties}
                aria-label={`Riquadro evidenza ${reviewLabel ? fieldLabel(reviewLabel) : ""}`}
              />
              <span
                className="review-bounding-label"
                style={{
                  left: `${reviewBox[0] * 100}%`,
                  top: `${reviewBox[1] * 100}%`,
                  "--bbox-color": bboxColor,
                } as CSSProperties}
              >
                {reviewLabel ? fieldLabel(reviewLabel) : "Evidenza"}
                {typeof reviewConfidence === "number" && ` · ${(reviewConfidence * 100).toFixed(0)}%`}
              </span>
            </>
          )}
          {loading && (
            <div className="simple-viewer-loading">
              <LoaderCircle className="spin" size={22} />
              <span>Caricamento pagina</span>
            </div>
          )}
          {error && <div className="simple-viewer-error">{error}</div>}
        </div>
      </div>
      <div className="simple-viewer-footer">
        <FileText size={14} />
        <span>{validBox ? "Evidenza selezionata" : "Visualizzazione documento"}</span>
        {reviewLabel && validBox && <b>{fieldLabel(reviewLabel)}</b>}
      </div>
    </div>
  );
}
