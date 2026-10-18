import { FormEvent, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle, CalendarClock, Check, Clock, FileVideo, History, KeyRound, Loader2,
  LogOut, Play, RefreshCw, Settings, Sparkles, Upload, Video,
} from "lucide-react";
import { api, ApiFailure, Category, Dashboard, Draft, Job, Playlist } from "@/lib/api";

type View = "overview" | "upload" | "drafts" | "schedule" | "history" | "settings";
type Action = (name: string, operation: () => Promise<unknown>, reload?: boolean) => Promise<void>;

const ACTIVE = new Set(["queued", "scheduled", "uploading", "retry_pending", "processing", "verifying"]);
const statusLabel: Record<string, string> = {
  draft: "Draft", ready: "Ready", queued: "Queued", scheduled: "Scheduled", uploading: "Uploading",
  processing: "Processing", verifying: "Verifying", uploaded: "Published", failed: "Failed",
  retry_pending: "Retry pending", cancelled: "Cancelled",
};

export default function Index() {
  const [operator, setOperator] = useState<{ required: boolean; authenticated: boolean } | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [view, setView] = useState<View>("overview");
  const [selected, setSelected] = useState<Draft | null>(null);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const refreshing = useRef(false);
  const selectedId = selected?.id;

  const checkOperator = useCallback(async () => {
    try {
      const value = await api.operatorStatus();
      setOperator(value);
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void checkOperator(), 0);
    return () => window.clearTimeout(timer);
  }, [checkOperator]);

  const refresh = useCallback(async () => {
    if (refreshing.current || (operator?.required && !operator.authenticated)) return;
    refreshing.current = true;
    try {
      const nextDashboard = await api.dashboard();
      setDashboard(nextDashboard);
      setLastUpdated(new Date(nextDashboard.server_time));
      setError("");
    } catch (caught) {
      const failure = caught as ApiFailure;
      if (failure.code === "operator_authentication_required") {
        setOperator({ required: true, authenticated: false });
      } else {
        setError(failure.message || "Refresh failed");
      }
    } finally {
      refreshing.current = false;
    }
  }, [operator]);

  const hasUploading = dashboard?.jobs.some(job => ["uploading", "processing", "verifying"].includes(job.status)) ?? false;
  const hasActive = dashboard?.jobs.some(job => ACTIVE.has(job.status)) ?? false;

  useEffect(() => {
    if (!operator?.authenticated && operator?.required) return;
    let timer = 0;
    let stopped = false;
    const schedule = () => {
      if (stopped || document.hidden) return;
      const delay = hasUploading ? 3_000 : hasActive ? 10_000 : 30_000;
      timer = window.setTimeout(async () => { await refresh(); schedule(); }, delay);
    };
    timer = window.setTimeout(async () => { await refresh(); schedule(); }, 0);
    const visibility = () => {
      window.clearTimeout(timer);
      if (!document.hidden) void refresh().finally(schedule);
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [hasActive, hasUploading, operator?.authenticated, operator?.required, refresh]);

  useEffect(() => {
    if (!selectedId || !dashboard?.auth.authenticated) {
      return;
    }
    let cancelled = false;
    Promise.all([api.playlists(), api.categories()])
      .then(([playlistData, categoryData]) => {
        if (!cancelled) { setPlaylists(playlistData.playlists); setCategories(categoryData.categories); }
      })
      .catch(caught => { if (!cancelled) setError((caught as Error).message); });
    return () => { cancelled = true; };
  }, [dashboard?.auth.authenticated, selectedId]);

  const act: Action = async (name, operation, reload = true) => {
    setBusy(name); setError("");
    try {
      await operation();
      if (reload) {
        await refresh();
        if (selectedId) setSelected((await api.draft(selectedId)).draft);
      }
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Something went wrong"); }
    finally { setBusy(""); }
  };

  const openDraft = async (draft: Draft) => {
    setBusy("open");
    try { setSelected((await api.draft(draft.id)).draft); setView("drafts"); }
    catch (caught) { setError((caught as Error).message); }
    finally { setBusy(""); }
  };

  if (!operator || (operator.required && !operator.authenticated)) {
    return <OperatorLogin loading={!operator} error={error} onLogin={async password => {
      setBusy("operator-login"); setError("");
      try { await api.operatorLogin(password); setOperator({ required: true, authenticated: true }); }
      catch (caught) { setError((caught as Error).message); }
      finally { setBusy(""); }
    }} busy={busy === "operator-login"}/>;
  }

  const drafts = dashboard?.drafts ?? [];
  const jobs = dashboard?.jobs ?? [];
  const auth = dashboard?.auth ?? { authenticated: false, channel: null };
  const checks = dashboard?.checks ?? {};
  const counts = summarize(drafts, jobs);

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span><Video size={22}/></span><div>StudioPilot<small>YouTube operations</small></div></div>
      <nav>
        <Nav active={view === "overview"} onClick={() => setView("overview")} icon={<Play/>}>Overview</Nav>
        <Nav active={view === "upload"} onClick={() => setView("upload")} icon={<Upload/>}>Upload videos</Nav>
        <Nav active={view === "drafts"} onClick={() => { setSelected(null); setView("drafts"); }} icon={<FileVideo/>}>Draft library <em>{counts.drafts}</em></Nav>
        <Nav active={view === "schedule"} onClick={() => setView("schedule")} icon={<CalendarClock/>}>Jobs & schedule <em>{counts.active}</em></Nav>
        <Nav active={view === "history"} onClick={() => setView("history")} icon={<History/>}>Upload history</Nav>
        <Nav active={view === "settings"} onClick={() => setView("settings")} icon={<Settings/>}>Settings</Nav>
      </nav>
      <div className={`account ${auth.authenticated ? "connected" : ""}`}>
        <span className="account-dot"/><div><strong>{auth.authenticated ? auth.channel?.title : "YouTube not connected"}</strong><small>{auth.authenticated ? "Channel connected" : "Publishing is disabled"}</small></div>
      </div>
    </aside>
    <main>
      <header><div><small>WORKSPACE</small><h1>{titleFor(view)}</h1>{lastUpdated ? <span className="last-updated">Updated {lastUpdated.toLocaleTimeString()}</span> : null}</div><button className="icon-button" onClick={() => void refresh()} aria-label="Refresh"><RefreshCw size={18}/></button></header>
      {error ? <div className="error-banner"><AlertCircle size={18}/><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error">x</button></div> : null}
      {dashboard && !checks.worker_online && <div className="warning-banner"><AlertCircle size={18}/><span>The upload worker is offline. Draft editing works, but queued jobs will wait.</span></div>}
      {view === "overview" && <Overview counts={counts} drafts={drafts} jobs={jobs} auth={auth} openDraft={openDraft} setView={setView}/>}
      {view === "upload" && <UploadPanel busy={busy} upload={files => act("upload", async () => {
        const queue = [...files]; let latest: Draft | null = null;
        const workers = Array.from({ length: Math.min(2, queue.length) }, async () => {
          while (queue.length) { const file = queue.shift(); if (file) latest = (await api.createDraft(file)).draft; }
        });
        await Promise.all(workers);
        if (latest) await openDraft(latest);
      })}/>}
      {view === "drafts" && (selected
        ? <DraftEditor draft={selected} busy={busy} close={() => setSelected(null)} act={act} setDraft={setSelected} playlists={auth.authenticated ? playlists : []} categories={auth.authenticated ? categories : []} canPublish={auth.authenticated}/>
        : <DraftList drafts={drafts} open={openDraft} busy={busy} queueBatch={ids => act("batch", () => api.batch(ids))}/>) }
      {view === "schedule" && <Jobs jobs={jobs} drafts={drafts} busy={busy} act={act}/>}
      {view === "history" && <HistoryPanel drafts={drafts}/>}
      {view === "settings" && <SettingsPanel checks={checks} auth={auth} act={act} operatorRequired={operator.required} operatorLogout={async () => { await api.operatorLogout(); setOperator({ required: true, authenticated: false }); }}/>}
    </main>
  </div>;
}

function OperatorLogin({ loading, error, onLogin, busy }: { loading: boolean; error: string; onLogin: (password: string) => Promise<void>; busy: boolean }) {
  const [password, setPassword] = useState("");
  const submit = (event: FormEvent) => { event.preventDefault(); if (password) void onLogin(password); };
  return <main className="login-screen"><form className="login-panel" onSubmit={submit}><span className="login-icon"><KeyRound/></span><h1>StudioPilot</h1><p>Enter the operator password to access drafts, credentials, and publishing controls.</p>{error ? <div className="error-banner"><AlertCircle size={16}/><span>{error}</span></div> : null}<label>Operator password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} disabled={loading || busy} autoFocus/></label><button className="primary full" disabled={!password || loading || busy}>{busy || loading ? <Loader2 className="spin"/> : <KeyRound/>} Sign in</button></form></main>;
}

function summarize(drafts: Draft[], jobs: Job[]) {
  const result = { drafts: 0, active: 0, uploaded: 0, failed: 0 };
  for (const draft of drafts) {
    if (["draft", "ready"].includes(draft.status)) result.drafts += 1;
    if (draft.status === "uploaded") result.uploaded += 1;
  }
  for (const job of jobs) {
    if (ACTIVE.has(job.status)) result.active += 1;
    if (job.status === "failed") result.failed += 1;
  }
  return result;
}

function titleFor(view: View) {
  const titles: Record<View, string> = {
    overview: "Operations overview",
    upload: "Add videos",
    drafts: "Draft library",
    schedule: "Jobs & schedule",
    history: "Upload history",
    settings: "Settings",
  };
  return titles[view];
}
function Nav({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) { return <button className={active ? "active" : ""} onClick={onClick}>{icon}<span>{children}</span></button>; }

function Overview({ counts, drafts, jobs, auth, openDraft, setView }: { counts: ReturnType<typeof summarize>; drafts: Draft[]; jobs: Job[]; auth: Dashboard["auth"]; openDraft: (draft: Draft) => void; setView: (view: View) => void }) { return <>
  <section className="hero"><div><p>YOUR CONTENT PIPELINE</p><h2>Prepare, approve,<br/>then <i>publish.</i></h2><span>Every video remains a durable draft until the worker uploads it and YouTube confirms processing.</span><button className="primary" onClick={() => setView("upload")}><Upload size={17}/> Add videos</button></div><div className="orbit"><Video size={54}/></div></section>
  {!auth.authenticated ? <section className="connect-card"><div className="youtube-icon"><Video/></div><div><strong>Connect your YouTube channel</strong><p>Draft preparation works now. Provider publishing stays disabled until OAuth succeeds.</p></div><button onClick={() => setView("settings")}>Connect channel</button></section> : null}
  <section className="metric-grid"><Metric label="Drafts to review" value={counts.drafts} detail="Needs operator approval"/><Metric label="Active jobs" value={counts.active} detail="Queued through verification"/><Metric label="Published" value={counts.uploaded} detail="Processing confirmed"/><Metric label="Needs attention" value={counts.failed} detail="Visible failures" warning={counts.failed > 0}/></section>
  <PipelineStrip drafts={drafts} jobs={jobs}/>
  <section className="split"><div className="panel"><PanelTitle title="Recent drafts" action="View all" onClick={() => setView("drafts")}/>{drafts.slice(0, 4).map(draft => <DraftRow key={draft.id} draft={draft} onClick={() => openDraft(draft)}/>)}{!drafts.length ? <Empty text="No drafts yet. Upload a video to begin."/> : null}</div><div className="panel"><PanelTitle title="Recent activity" action="View jobs" onClick={() => setView("schedule")}/>{jobs.slice(0, 5).map(job => <div className="activity" key={job.id}><span className={`status-dot ${job.status}`}/><div><strong>{statusLabel[job.status] || job.status}</strong><small>{new Date(job.run_at).toLocaleString()}</small></div><b>{job.progress}%</b></div>)}{!jobs.length ? <Empty text="Job activity will appear here."/> : null}</div></section>
  </>; }

function PipelineStrip({ drafts, jobs }: { drafts: Draft[]; jobs: Job[] }) {
  const stages = [
    ["Draft", drafts.filter(value => ["draft", "ready"].includes(value.status)).length],
    ["Queued", jobs.filter(value => ["queued", "scheduled", "retry_pending"].includes(value.status)).length],
    ["Uploading", jobs.filter(value => value.status === "uploading").length],
    ["Verifying", jobs.filter(value => ["processing", "verifying"].includes(value.status)).length],
    ["Published", drafts.filter(value => value.status === "uploaded").length],
  ] as const;
  return <section className="pipeline-strip" aria-label="Publishing pipeline">{stages.map(([label, count], index) => <div key={label}><small>{index + 1}</small><span>{label}</span><strong>{count}</strong></div>)}</section>;
}

function Metric({ label, value, detail, warning }: { label: string; value: number; detail: string; warning?: boolean }) { return <div className={`metric ${warning ? "warning" : ""}`}><small>{label}</small><strong>{value}</strong><span>{detail}</span></div>; }
function PanelTitle({ title, action, onClick }: { title: string; action?: string; onClick?: () => void }) { return <div className="panel-title"><h3>{title}</h3>{action ? <button onClick={onClick}>{action} <span aria-hidden="true">-&gt;</span></button> : null}</div>; }
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div>; }
const DraftRow = memo(function DraftRow({ draft, onClick }: { draft: Draft; onClick: () => void }) { return <button className="draft-row" onClick={onClick}><span className="video-thumb"><FileVideo/></span><div><strong>{draft.title || draft.filename}</strong><small>{draft.filename} / {(draft.file_size / 1048576).toFixed(1)} MB</small></div><span className={`pill ${draft.status}`}>{statusLabel[draft.status] || draft.status}</span></button>; });

function UploadPanel({ upload, busy }: { upload: (files: File[]) => void; busy: string }) { const [drag, setDrag] = useState(false); return <section className="panel upload-panel"><div className="upload-copy"><span><Upload/></span><h2>Bring in your next videos</h2><p>MP4, MOV, M4V, WebM, MKV or AVI. Two files are streamed at a time to limit memory, disk, and network pressure.</p></div><label className={drag ? "dropzone drag" : "dropzone"} onDragOver={event => { event.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={event => { event.preventDefault(); setDrag(false); const files = Array.from(event.dataTransfer.files); if (files.length) upload(files); }}><input multiple type="file" accept="video/mp4,video/quicktime,video/webm,.mkv,.avi,.m4v" onChange={event => { const files = Array.from(event.target.files || []); if (files.length) upload(files); }}/>{busy === "upload" ? <Loader2 className="spin"/> : <Upload/>}<strong>{busy === "upload" ? "Saving and checking videos..." : "Drop one or more videos here"}</strong><span>or click to choose files</span></label></section>; }

function DraftList({ drafts, open, busy, queueBatch }: { drafts: Draft[]; open: (draft: Draft) => void; busy: string; queueBatch: (ids: string[]) => void }) {
  const eligible = useMemo(() => drafts.filter(value => ["draft", "ready", "failed", "cancelled"].includes(value.status) && !value.youtube_video_id), [drafts]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const eligibleSet = useMemo(() => new Set(eligible.map(value => value.id)), [eligible]);
  const selected = selectedIds.filter(id => eligibleSet.has(id));
  return <section className="panel"><div className="library-toolbar"><PanelTitle title={`${drafts.length} video drafts`}/><button className="primary" disabled={!selected.length || !!busy} onClick={() => queueBatch(selected)}><Upload size={15}/> Queue {selected.length || "selected"}</button></div>{drafts.map(draft => <div className="selectable-draft" key={draft.id}><input type="checkbox" aria-label={`Select ${draft.title || draft.filename}`} checked={selected.includes(draft.id)} disabled={!eligibleSet.has(draft.id)} onChange={event => setSelectedIds(current => event.target.checked ? [...current, draft.id] : current.filter(id => id !== draft.id))}/><DraftRow draft={draft} onClick={() => open(draft)}/></div>)}{!drafts.length ? <Empty text="Your draft library is empty."/> : null}</section>;
}

function DraftEditor({ draft, setDraft, close, busy, act, playlists, categories, canPublish }: { draft: Draft; setDraft: (draft: Draft) => void; close: () => void; busy: string; act: Action; playlists: Playlist[]; categories: Category[]; canPublish: boolean }) {
  const patch = (value: Partial<Draft>) => setDraft({ ...draft, ...value });
  const save = () => act("save", async () => setDraft((await api.updateDraft(draft.id, { title: draft.title, description: draft.description, tags: draft.tags, privacy_status: draft.privacy_status, category_id: draft.category_id, playlist_id: draft.playlist_id, scheduled_at: draft.scheduled_at })).draft));
  const queue = () => {
    if (draft.privacy_status === "public" && !window.confirm("Queue this video as public? It will become externally visible after YouTube processing.")) return;
    void act("publish", () => api.createJob(draft.id, draft.scheduled_at || undefined));
  };
  return <div className="editor"><button className="back" onClick={close}>&lt;- Back to drafts</button><div className="editor-head"><div><span className={`pill ${draft.status}`}>{statusLabel[draft.status]}</span><h2>{draft.title || draft.filename}</h2><p>{draft.filename} / metadata: {draft.metadata_source}{draft.manually_edited ? " + manual edits" : ""}</p></div><button className="primary" disabled={!!busy} onClick={save}>{busy === "save" ? <Loader2 className="spin"/> : <Check/>} Save draft</button></div>
    <div className="editor-grid"><section className="panel form-panel"><h3>Video details</h3><label>Title <small>{draft.title.length}/100</small><input value={draft.title} maxLength={100} onChange={event => patch({ title: event.target.value })}/></label><label>Description <small>{draft.description.length}/5000</small><textarea rows={9} value={draft.description} maxLength={5000} onChange={event => patch({ description: event.target.value })}/></label><label>Tags<input value={draft.tags.join(", ")} onChange={event => patch({ tags: event.target.value.split(",").map(value => value.trim()).filter(Boolean) })}/></label><div className="form-row"><label>Privacy<select value={draft.privacy_status} onChange={event => patch({ privacy_status: event.target.value as Draft["privacy_status"] })}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></label><label>Category<select value={draft.category_id} onChange={event => patch({ category_id: event.target.value })}>{categories.length ? categories.map(category => <option key={category.id} value={category.id}>{category.title}</option>) : <option value={draft.category_id}>Category {draft.category_id}</option>}</select></label></div><label>Playlist<select value={draft.playlist_id || ""} onChange={event => patch({ playlist_id: event.target.value || null })}><option value="">No playlist</option>{playlists.map(playlist => <option key={playlist.id} value={playlist.id}>{playlist.title}</option>)}</select></label></section>
      <aside className="tools"><section className="panel"><h3><Sparkles/> Preparation</h3><ToolButton busy={busy === "metadata"} onClick={() => void act("metadata", () => api.generateMetadata(draft.id))} title="Generate metadata" note={draft.metadata_source === "ai" ? "AI-generated; review before publishing" : "Uses a local editable template when AI is unavailable"}/><ToolButton busy={busy === "transcript"} onClick={() => void act("transcript", () => api.generateTranscript(draft.id))} title="Generate transcript" note={draft.transcript?.status || "Long videos are chunked locally with FFmpeg"}/><ToolButton busy={busy === "thumbnails"} onClick={() => void act("thumbnails", () => api.generateThumbnails(draft.id))} title="Create thumbnails" note={`${draft.thumbnails?.length || 0} candidates`}/><label className="custom-thumbnail">Upload thumbnail<input type="file" accept="image/jpeg,image/png" onChange={event => { const file = event.target.files?.[0]; if (file) void act("custom-thumbnail", () => api.uploadThumbnail(draft.id, file)); }}/></label></section><section className="panel publish-card"><h3><Clock/> Publishing</h3><label>Schedule time (optional)<input type="datetime-local" value={draft.scheduled_at?.slice(0, 16) || ""} onChange={event => patch({ scheduled_at: event.target.value ? new Date(event.target.value).toISOString() : null })}/></label><button className="primary full" disabled={!!busy || !canPublish || draft.status === "uploaded"} onClick={queue}>{draft.scheduled_at ? "Schedule upload" : "Queue for upload"}</button><small>{canPublish ? "The worker uploads, post-processes, and verifies the provider result." : "Connect YouTube before queueing a provider action."}</small></section></aside>
    </div>{draft.transcript ? <section className="panel transcript"><h3>Transcript</h3><textarea rows={8} value={draft.transcript.text} onChange={event => setDraft({ ...draft, transcript: { ...draft.transcript!, text: event.target.value } })}/><button onClick={() => void act("save-transcript", () => api.saveTranscript(draft.id, draft.transcript!.text))}>Save transcript</button></section> : null}
    {draft.thumbnails?.length ? <section className="panel thumbnail-panel"><h3>Thumbnail candidates</h3><div className="thumbnail-grid">{draft.thumbnails.map(thumbnail => <button key={thumbnail.id} className={thumbnail.selected ? "selected" : ""} onClick={() => void act("select-thumb", () => api.selectThumbnail(draft.id, thumbnail.id))}><img src={api.assetUrl(thumbnail.url)} alt={thumbnail.source}/><span>{thumbnail.selected ? "Selected" : thumbnail.source}</span></button>)}</div></section> : null}
  </div>;
}

function ToolButton({ busy, onClick, title, note }: { busy: boolean; onClick: () => void; title: string; note: string }) { return <button className="tool-button" onClick={onClick} disabled={busy}>{busy ? <Loader2 className="spin"/> : <Sparkles/>}<div><strong>{title}</strong><small>{note}</small></div><span>-&gt;</span></button>; }

function Jobs({ jobs, drafts, busy, act }: { jobs: Job[]; drafts: Draft[]; busy: string; act: Action }) {
  const draftNames = useMemo(() => new Map(drafts.map(draft => [draft.id, draft.title || draft.filename])), [drafts]);
  return <section className="panel"><PanelTitle title="Upload job queue" action="Adaptive refresh"/>{jobs.map(job => <div className="job-row" key={job.id}><span className={`status-dot ${job.status}`}/><div><strong>{draftNames.get(job.draft_id) || "Video upload"}</strong><small>{statusLabel[job.status] || job.status} / attempt {job.retry_count + 1} / {new Date(job.run_at).toLocaleString()}</small>{job.processing_status ? <small>Provider processing: {job.processing_status}</small> : null}{job.last_error ? <p>{job.last_error}</p> : null}</div><div className="progress" aria-label={`${job.progress}% complete`}><span style={{ width: `${job.progress}%` }}/></div>{job.status === "failed" ? <button disabled={!!busy} onClick={() => void act("retry", () => api.retry(job.id))}>Retry</button> : null}{["queued", "scheduled", "retry_pending"].includes(job.status) ? <button onClick={() => void act("cancel", () => api.cancel(job.id))}>Cancel</button> : null}{job.status === "uploaded" ? <Check/> : null}</div>)}{!jobs.length ? <Empty text="No upload jobs yet."/> : null}</section>;
}

function HistoryPanel({ drafts }: { drafts: Draft[] }) { const items = drafts.filter(draft => ["uploaded", "failed"].includes(draft.status)); return <section className="panel"><h3>Verified upload outcomes</h3>{items.map(draft => <div className="history-row" key={draft.id}><span className={`status-dot ${draft.status}`}/><div><strong>{draft.title}</strong><small>{new Date(draft.created_at).toLocaleDateString()} / {statusLabel[draft.status]}</small></div>{draft.youtube_url ? <a href={draft.youtube_url} target="_blank" rel="noreferrer">Open on YouTube</a> : null}</div>)}{!items.length ? <Empty text="Confirmed uploads and failures will appear here."/> : null}</section>; }

function SettingsPanel({ checks, auth, act, operatorRequired, operatorLogout }: { checks: Record<string, boolean>; auth: Dashboard["auth"]; act: Action; operatorRequired: boolean; operatorLogout: () => Promise<void> }) {
  const connect = () => act("connect", async () => { const { auth_url } = await api.login(); window.location.href = auth_url; }, false);
  const optional = new Set(["ai_configured", "hai_connector_configured"]);
  return <div className="settings-grid"><section className="panel"><h3>YouTube connection</h3><div className="setting-state"><Video/><div><strong>{auth.authenticated ? auth.channel?.title : "No channel connected"}</strong><small>{auth.authenticated ? "OAuth credentials stored encrypted" : "Official Google OAuth is required to publish"}</small></div></div>{auth.authenticated ? <button onClick={() => void act("logout", () => api.logout())}><LogOut/> Disconnect</button> : <button className="primary" onClick={() => void connect()}><Video/> Connect with Google</button>}</section><section className="panel"><h3>Service readiness</h3>{Object.entries(checks).map(([name, ok]) => <div className={`check ${ok ? "ok" : optional.has(name) ? "optional" : "missing"}`} key={name}>{ok ? <Check/> : <AlertCircle/>}<span>{name.replace(/_/g, " ")}</span><b>{ok ? "Ready" : optional.has(name) ? "Optional" : "Not ready"}</b></div>)}</section><section className="panel note"><h3>HAI connector</h3><p>{checks.hai_connector_configured ? "The token-isolated HAI connector is active. Mutating requests require idempotency, task ID, and approval-binding headers." : "The HAI connector is disabled until HAI_CONNECTOR_ENABLED and a 32+ character HAI_CONNECTOR_TOKEN are configured."}</p></section><section className="panel note"><h3>Operator safeguards</h3><p>Uploads use durable leases and resumable sessions. StudioPilot marks a video published only after YouTube confirms processing. Thumbnail and playlist failures remain separate warnings.</p>{operatorRequired ? <button onClick={() => void operatorLogout()}><LogOut/> Lock operator session</button> : null}</section></div>;
}
