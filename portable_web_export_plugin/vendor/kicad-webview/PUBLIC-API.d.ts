/* Copyright (c) 2026 wayri. SPDX-License-Identifier: MPL-2.0 */
export as namespace KiCadWebView;
export declare const EMBED_API_VERSION: '1.0-beta';
export type Theme = 'light' | 'dark';
export type HighlightMode = 'dim' | 'bright' | 'isolate';
export type HighlightColor = 'accent' | 'source';
export interface HighlightStyle { mode: HighlightMode; color: HighlightColor; }
export type LayerPreset = 'all' | 'none' | 'front' | 'back' | 'copper';
export interface LayerState { layers: string[]; visible: string[]; focused: string | null; focusMode: 'dim' | 'isolate'; canFocus: boolean; canRestore: boolean; }
export type BoardAppearance = 'realistic' | 'layers' | 'translucent';
export interface RenderActivityStats { documentVisible: boolean; intersecting: boolean; hasSize: boolean; contextAvailable: boolean; paused: boolean; dirty: boolean; pending: boolean; requestCount: number; scheduledFrames: number; renderCallbacks: number; suppressedInvalidations: number; cancelledFrames: number; skippedFrames: number; resumeCount: number; observesIntersection: boolean; }
export interface SelectionWorkloadStats { netOnlyUpdates: number; netRecordsScanned: number; netBoundsAvoided: number; boundsEvaluations: number; outlineVerticesWritten: number; }
export interface RenderStats { renderActivity: RenderActivityStats; selectionWorkload: SelectionWorkloadStats; appearance: BoardAppearance; drawCalls: number; renderCount: number; loadedModelCount: number; componentCount: number; modelUpdates: { requestCount: number; flushCount: number; pending: boolean; cpuMilliseconds: number }; [key: string]: unknown; }
export type Camera3DPreset = 'top' | 'bottom' | 'front' | 'back' | 'left' | 'right' | 'isometric';
export type DrawingView = 'pcb' | 'schematic' | '3d' | 'manufacturing';
export interface ProjectFile { path: string; url: string; }
export interface ProjectFileInfo { path: string; url?: string; }
export type DeepReadonly<T> = T extends object ? { readonly [K in keyof T]: DeepReadonly<T[K]> } : T;
export interface ProjectManifest { files: ProjectFile[]; entry?: string; }
export interface LocalSource { path: string; source?: string; bytes?: Uint8Array | ArrayBuffer; }
export interface LoadOptions {
  view?: DrawingView; file?: string; ref?: string; signal?: AbortSignal;
  baseURL?: string; credentials?: 'omit' | 'same-origin';
}
export interface ViewerOptions { theme?: Theme; appearance?: BoardAppearance; highlightStyle?: HighlightMode; highlightColor?: HighlightColor; inspectOnSelect?: boolean; assetPaths?: string[]; loadAsset?: (path: string) => unknown | Promise<unknown>; }
export interface Part { id: string; uuid: string; reference: string; value: string; footprint: string; layer: string; schematicUuid?: string; }
export interface SavedNet { id: string; name: string; layers: string[]; count: number; }
export interface SheetLink { uuid: string; name: string; file: string; path: string | null; }
/** Saved world coordinates in mm; zoom is CSS pixels per mm. PCB/schematic only. */
export interface Camera3D { position: [number,number,number]; target: [number,number,number]; up: [number,number,number]; }
export interface Camera2D { center: { x: number; y: number }; zoom: number; flipped: boolean; }
export interface ReadyDetail { view: DrawingView; path: string; revision: string | null; warnings: string[]; }
export interface SelectedItem { uuid?: string; id?: string; kind?: string; netName?: string; ownerUuid?: string; reference?: string; pinNumber?: string | number; [key: string]: unknown; }
export interface SelectionDetail { item: SelectedItem | null; path: string; view: DrawingView; multi?: boolean; }
export interface AnalysisCell { x: number; y: number; width: number; height: number; value: number; }
export interface AnalysisField { id: string; name: string; unit: string; layer?: string; range: [number, number]; samples: AnalysisCell[]; }
export interface AnalysisData {
  schema: 'kicad-webview.analysis/v1'; coordinateSystem: 'kicad-mm'; board: { sha256: string; path?: string };
  provenance: { kind: 'computed' | 'measured' | 'illustrative'; tool: string; runId: string; generatedAt?: string; assumptions: string[] };
  fields: AnalysisField[];
}
export interface ViewerEvents {
  analysisprobe: CustomEvent<{probe:{x:number;y:number;z?:number;value:number;unit:string};path:string;view:'3d'}>;
  highlightstylechange: CustomEvent<HighlightStyle>;
  layerschange: CustomEvent<LayerState>;
  dispose: CustomEvent<null>;
  ready: CustomEvent<ReadyDetail>;
  select: CustomEvent<SelectionDetail>;
  error: CustomEvent<Error>;
  viewchange: CustomEvent<{ view: DrawingView; path: string }>;
  camerachange: CustomEvent<{ view: DrawingView; path: string; camera: Camera2D }>;
  measure: CustomEvent<unknown>;
  analysis: CustomEvent<{ fields: Pick<AnalysisField, 'id' | 'name' | 'unit'>[]; provenance: AnalysisData['provenance'] }>;
}
export declare class KiCadViewer extends EventTarget {
  constructor(target: string | HTMLElement, options?: ViewerOptions);
  readonly path: string | undefined; readonly kind: 'pcb' | 'schematic' | 'manufacturing' | undefined; readonly view: DrawingView | undefined;
  load(input: string | URL | ProjectManifest, options?: LoadOptions): Promise<boolean>;
  loadProject(input: string | URL | ProjectManifest, options?: LoadOptions): Promise<boolean>;
  loadFiles(files: Iterable<File | LocalSource>, options?: LoadOptions): Promise<boolean>;
  loadArchive(bytes: Uint8Array | ArrayBuffer, options?: LoadOptions): Promise<boolean>;
  loadSource(source: string, options?: LoadOptions & { path?: string; project?: ProjectManifest }): Promise<boolean>;
  getFiles(): ProjectFileInfo[]; openFile(path: string, options?: LoadOptions): Promise<boolean>;
  getParts(): Part[]; selectPart(id: string, options?: { locate?: boolean }): boolean;
  setInspectOnSelect(enabled: boolean): void;
  getSelection(): ViewSelection | null; getSelectionPosition(): {x:number;y:number;layer:string|null}|null; selectObject(id: string, options?: {locate?: boolean; pinNumber?: string | number}): boolean;
  getNets(): SavedNet[]; selectNet(idOrUniqueName: string, options?: { locate?: boolean }): boolean;
  getSheets(): SheetLink[]; clearSelection(): void; setInspectorOpen(open: boolean): void;
  setView(view: DrawingView, options?: {signal?: AbortSignal}): Promise<boolean>; fit(): void;
  /** Optional GPU-intensive studio presentation mode; returns the active quality after fallback. */
  setRenderQuality(quality: 'low'|'balanced'|'high'|'presentation'): 'low'|'balanced'|'high'|'presentation';
  setExplode(value:number):number;
  getExplode():number;
  setAppearance(appearance: BoardAppearance): BoardAppearance; getAppearance(): BoardAppearance | null; getRenderStats(): RenderStats | null;
  getCamera(): Camera2D | null; setCamera(camera: Camera2D): void; pickDemoFace(options?: {signal?: AbortSignal}): Promise<SelectedDemoFace>; rotate3D(direction: 'left'|'right'|'up'|'down'|'clockwise'|'counterclockwise', degrees?: number): boolean; getCamera3D(): Camera3D | null; setCamera3D(preset: Camera3DPreset | Camera3D): boolean;
  getLayers(): string[]; setLayers(layers: string[]): LayerState;
  getLayerState(): LayerState; setLayerPreset(preset: LayerPreset): LayerState;
  focusLayer(layer: string, options?: {mode?: 'dim'|'isolate'; fit?: boolean}): LayerState;
  clearLayerFocus(): LayerState; restoreLayerView(): LayerState; fitFocusedLayer(): boolean;
  setHighlightStyle(mode: HighlightMode, options?: {color?: HighlightColor}): HighlightStyle; getHighlightStyle(): HighlightStyle; setTheme(theme: Theme): void;
  setMeasuring(enabled: boolean): void;
  setAnalysis(input: AnalysisData | DeepReadonly<AnalysisData> | string): Promise<boolean>;
  getAnalysis(): DeepReadonly<AnalysisData> | null; setAnalysisField(id: string): void; clearAnalysis(): void;
  dispose(): void;
  addEventListener<K extends keyof ViewerEvents>(type: K, listener: (event: ViewerEvents[K]) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void;
}
export { KiCadViewer as Viewer };
export declare function registerKiCadViewer(tag?: string): void;
export declare function parseAnalysis(input: AnalysisData | DeepReadonly<AnalysisData> | string): Readonly<AnalysisData>;
export declare function analysisSourceHash(source: string): Promise<string>;
export interface ProjectOptions extends ViewerOptions { layout?: 'split' | 'single'; linkedSelection?: boolean; }
export interface ProjectEvents {
  ready: CustomEvent<ReadyDetail & { pane: 0 | 1 }>;
  select: CustomEvent<SelectionDetail & { pane: 0 | 1 }>;
  error: CustomEvent<{ pane: 0 | 1; error: Error }>;
  projectready: CustomEvent<{ files: ProjectFileInfo[] }>;
  panechange: CustomEvent<{ pane: 0 | 1 }>;
}
export declare class AdvancedKiCadViewer extends EventTarget {
  openSheetBrowser():Promise<boolean>;
  closeSheetBrowser():void;
  constructor(target: string | HTMLElement, options?: ProjectOptions);
  load(input: string | URL | ProjectManifest, options?: LoadOptions): Promise<boolean>;
  loadFiles(files: Iterable<File | LocalSource>, options?: LoadOptions): Promise<boolean>;
  loadArchive(bytes: Uint8Array | ArrayBuffer, options?: LoadOptions): Promise<boolean>;
  openFile(path: string, options?: { pane?: 0 | 1; signal?: AbortSignal }): Promise<boolean>;
  getFiles(): { path: string; url?: string }[]; getActiveViewer(): KiCadViewer;
  setActivePane(pane: 0 | 1): void; setLayout(layout: 'split' | 'single'): void;
  setNavigatorOpen(open: boolean): void; setTheme(theme: Theme): void;
  getViewState(): Promise<ViewState>; createViewLink(baseURL?: string | URL): Promise<string>; restoreViewState(state: ViewState, options?: {signal?: AbortSignal}): Promise<boolean>;
  dispose(): void;
  addEventListener<K extends keyof ProjectEvents>(type: K, listener: (event: ProjectEvents[K]) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void;
}
export { AdvancedKiCadViewer as ProjectViewer };
export declare function readZip(bytes: Uint8Array | ArrayBuffer, options?: { signal?: AbortSignal }): Promise<LocalSource[]>;
/** CAM parser's full result remains implementation-specific in this beta. */
export declare function parseManufacturing(source: string, options?: Record<string, unknown>): unknown;
/** Altium uses its provider-hosted beta embed; readiness is not native file parsing. */
export declare class AltiumViewer extends EventTarget {
  constructor(target: string | HTMLElement, options?: Record<string, unknown>);
  load(input: string | URL, options?: Record<string, unknown>): Promise<unknown>;
  dispose(): void;
}

export interface CarouselSlide {
  label: string; input?: string | URL | ProjectManifest; source?: string;
  options?: LoadOptions & { path?: string; project?: ProjectManifest };
  view?: DrawingView; camera?: Camera2D; camera3D?: Camera3DPreset;
  net?: string; clearSelection?: boolean;
}
export interface CarouselOptions { viewer: KiCadViewer; slides: CarouselSlide[]; interval?: number; }
export declare class ViewerCarousel extends EventTarget {
  constructor(target: string | HTMLElement, options: CarouselOptions);
  readonly index: number; readonly playing: boolean;
  show(index: number): Promise<boolean>; next(): Promise<boolean>; previous(): Promise<boolean>;
  play(): boolean; pause(): void; dispose(): void;
  addEventListener(type: 'slidechange', listener: (event: CustomEvent<{index: number; label: string}>) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: 'error', listener: (event: CustomEvent<{index: number; error: Error}>) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void;
}

export interface LinkedViewGroup extends EventTarget {
 readonly enabled: boolean; setEnabled(enabled: boolean): void; dispose(): void;
 addEventListener(type: 'link', listener: (event: CustomEvent<{source: KiCadViewer; target: KiCadViewer; kind: 'part'|'net'|'object'|'clear'}>) => void, options?: boolean | AddEventListenerOptions): void;
 addEventListener(type: 'linkerror', listener: (event: CustomEvent<{source: KiCadViewer; target: KiCadViewer; error: Error}>) => void, options?: boolean | AddEventListenerOptions): void;
 addEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void;
}
export interface ViewSelection { kind: string; uuid?: string; ownerUuid?: string; id?: string; netName?: string; pinNumber?: string | number; }
export declare function linkViewers(viewers: KiCadViewer[], options?: {enabled?: boolean}): LinkedViewGroup;
export interface SavedView {
  path: string; sha256: string; view: 'pcb' | 'schematic' | '3d';
  camera?: Camera2D; camera3D?: Camera3D; layers?: string[]; selection?: ViewSelection | null;
}
export interface ViewState {
  schema: 'kicad-webview.views/v1'; views: SavedView[];
  theme?: Theme; layout?: 'split' | 'single'; activePane?: number; linkedSelection?: boolean;
}
export interface RestoreViewOptions {
  signal?: AbortSignal; current?: () => boolean;
  openFile?: (index: number, path: string, signal?: AbortSignal) => boolean | Promise<boolean>;
}
export declare function captureViewState(viewers: KiCadViewer[], options?: Pick<ViewState,'theme'|'layout'|'activePane'|'linkedSelection'>): Promise<ViewState>;
export declare function restoreViewState(viewers: KiCadViewer[], state: ViewState, options?: RestoreViewOptions): Promise<boolean>;
export declare function validateViewState(state: unknown): ViewState;
export declare function createViewLink(baseURL: string | URL, state: ViewState): string;
export declare function parseViewLink(url: string | URL): ViewState | null;

export type DemoFaceDirection = 'top'|'bottom'|'front'|'back'|'left'|'right';
export interface DemoFaceFrame { shape?: 'face'|'component'; center: [number,number,number]; normal: [number,number,number] | null; width: number; height: number; up?: [number,number,number]; right?: [number,number,number]; }
export interface SelectedDemoFace extends DemoFaceFrame { token: string; shape: 'face'; normal: [number,number,number]; uuid: string; reference: string; triangles: number; }
export interface DemoPlacement { anchor?: {uuid?: string; reference?: string; face?: DemoFaceDirection}; face?: SelectedDemoFace | string; }
export interface DemoInput { id: string; type: 'press'|'release'|'change'; source: string; value?: number | boolean; cancelled?: boolean; uv?: {x: number; y: number}; code?: string; originalEvent?: Event; }
export interface DemoKeyBinding {
  id?: string; action?: 'press'|'toggle'|'increment'|'decrement'; repeat?: boolean; preventDefault?: boolean;
  shiftKey?: boolean; altKey?: boolean; ctrlKey?: boolean; metaKey?: boolean;
  onDown?: (input: Partial<DemoInput>) => unknown; onUp?: (input: Partial<DemoInput>) => unknown;
}
export declare class DemoController extends EventTarget {
  constructor(viewer: KiCadViewer);
  readonly active: boolean; readonly suspended: boolean; readonly disposed: boolean;
  addLED(id: string, options: DemoPlacement & {on?: boolean; brightness?: number; color?: string}): string;
  setLED(id: string, patch: boolean | {on?: boolean; brightness?: number; color?: string}): Record<string,unknown>;
  addDisplay(id: string, options: DemoPlacement & {mode?: 'matrix'|'oled'|'lcd'|'tft'; width?: number; height?: number; onPress?: (input: DemoInput) => unknown; onRelease?: (input: DemoInput) => unknown}): string;
  drawDisplay(id: string, draw: (context: CanvasRenderingContext2D, canvas: HTMLCanvasElement) => void): boolean;
  writeImage(id: string, image: CanvasImageSource): boolean;
  setPixels(id: string, pixels: Uint8Array | Uint8ClampedArray, options?: {format?: 'rgba'|'mono'|'mono1'; foreground?: string; background?: string}): boolean;
  addButton(id: string, options: DemoPlacement & {label?: string; onPress?: (input: DemoInput) => unknown; onRelease?: (input: DemoInput) => unknown}): string;
  addKnob(id: string, options: DemoPlacement & {min?: number; max?: number; step?: number; value?: number; onChange?: (input: DemoInput) => unknown}): string;
  setKnob(id: string, value: number, options?: {source?: string}): boolean;
  press(id: string, detail?: Partial<DemoInput>): boolean; release(id: string, detail?: Partial<DemoInput>): boolean;
  change(id: string, delta: number, options?: {source?: string}): boolean; toggle(id: string, options?: {source?: string}): boolean;
  bindKey(code: string, binding: DemoKeyBinding): () => void; unbindKey(code: string): boolean;
  focus(): boolean; getFace(id: string): DemoFaceFrame; getState(id: string): Record<string,unknown>;
  remove(id: string): boolean; suspend(reason?: string): void; dispose(): void;
  addEventListener(type: 'input', listener: (event: CustomEvent<DemoInput>) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: 'error', listener: (event: CustomEvent<{id?: string; phase: string; error: Error}>) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: 'suspend', listener: (event: CustomEvent<{reason: string}>) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void;
}

export * from './hierarchy.js';

export interface StandaloneHTMLOptions { viewerScript: string; licenseText: string; files: {path: string; bytes: Uint8Array}[]; title?: string; view?: DrawingView; theme?: Theme; highlightStyle?: HighlightMode; highlightColor?: HighlightColor; appearance?: BoardAppearance; }
/** Generate an offline HTML string in caller memory. Include the matching viewer script, license and source notices. */
export declare function createStandaloneHTML(options: StandaloneHTMLOptions): string;

export * from './wayricad-results.js';

export * from './bom.js';
