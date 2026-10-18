import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CalendarClock, Check, Clock, FileVideo, History, Loader2, LogOut, Play, RefreshCw, Settings, Sparkles, Upload, Video } from "lucide-react";
import { api, ApiFailure, Draft, Job } from "@/lib/api";

type View = "overview" | "upload" | "drafts" | "schedule" | "history" | "settings";

const statusLabel: Record<string, string> = { draft: "Draft", ready: "Ready", queued: "Queued", scheduled: "Scheduled", uploading: "Uploading", uploaded: "Published", failed: "Failed", retry_pending: "Retry pending", cancelled: "Cancelled" };

export default function Index() {
  const [view, setView] = useState<View>("overview");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<Draft | null>(null);
  const [auth, setAuth] = useState<{ authenticated: boolean; channel: { title: string } | null }>({ authenticated: false, channel: null });
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const selectedId = selected?.id;

  const refresh = useCallback(async () => {
    try {
      const [draftData, jobData, authData, settings] = await Promise.all([api.drafts(), api.jobs(), api.auth(), api.settings()]);
      setDrafts(draftData.drafts); setJobs(jobData.jobs); setAuth(authData); setChecks(settings.checks);
      if (selectedId) {
        const updated = await api.draft(selectedId); setSelected(updated.draft);
      }
    } catch (e) { setError((e as Error).message); }
  }, [selectedId]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);
  useEffect(() => { const timer = window.setInterval(refresh, 5000); return () => window.clearInterval(timer); }, [refresh]);

  const act = async (name: string, fn: () => Promise<unknown>, reload = true) => {
    setBusy(name); setError("");
    try { await fn(); if (reload) await refresh(); }
    catch (e) { setError(e instanceof ApiFailure ? e.message : "Something went wrong"); }
    finally { setBusy(""); }
  };

  const openDraft = async (draft: Draft) => {
    setBusy("open");
    try { setSelected((await api.draft(draft.id)).draft); setView("drafts"); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };

  const counts = useMemo(() => ({ drafts: drafts.filter(d => ["draft", "ready"].includes(d.status)).length,
    active: jobs.filter(j => ["queued", "scheduled", "uploading", "retry_pending"].includes(j.status)).length,
    uploaded: drafts.filter(d => d.status === "uploaded").length, failed: jobs.filter(j => j.status === "failed").length }), [drafts, jobs]);

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
      <header><div><small>WORKSPACE</small><h1>{view === "overview" ? "Good to see you" : ({ upload: "Add videos", drafts: "Draft library", schedule: "Jobs & schedule", history: "Upload history", settings: "Settings" } as Record<string,string>)[view]}</h1></div><button className="icon-button" onClick={refresh} aria-label="Refresh"><RefreshCw size={18}/></button></header>
      {error && <div className="error-banner"><AlertCircle size={18}/><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
      {view === "overview" && <Overview counts={counts} drafts={drafts} jobs={jobs} auth={auth} openDraft={openDraft} setView={setView}/>}
      {view === "upload" && <UploadPanel busy={busy} upload={(files) => act("upload", async () => { let latest: Draft | null = null; for (const file of files) latest = (await api.createDraft(file)).draft; if (latest) await openDraft(latest); }, false)}/>}
      {view === "drafts" && (selected ? <DraftEditor draft={selected} busy={busy} close={() => setSelected(null)} act={act} setDraft={setSelected}/> : <DraftList drafts={drafts} open={openDraft}/>) }
      {view === "schedule" && <Jobs jobs={jobs} drafts={drafts} busy={busy} act={act}/>}
      {view === "history" && <HistoryPanel drafts={drafts}/>}
      {view === "settings" && <SettingsPanel checks={checks} auth={auth} act={act}/>}
    </main>
  </div>;
}

function Nav({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) { return <button className={active ? "active" : ""} onClick={onClick}>{icon}<span>{children}</span></button>; }

function Overview({ counts, drafts, jobs, auth, openDraft, setView }: any) { return <>
  <section className="hero"><div><p>YOUR CONTENT PIPELINE</p><h2>From raw footage<br/>to <i>published.</i></h2><span>Prepare metadata, transcripts, thumbnails and publishing jobs without losing track of the real YouTube state.</span><button className="primary" onClick={() => setView("upload")}><Upload size={17}/> Add videos</button></div><div className="orbit"><Video size={54}/></div></section>
  {!auth.authenticated && <section className="connect-card"><div className="youtube-icon"><Video/></div><div><strong>Connect your YouTube channel</strong><p>Draft preparation works now. Connect Google before a worker can publish.</p></div><button onClick={() => setView("settings")}>Connect channel</button></section>}
  <section className="metric-grid"><Metric label="Drafts to review" value={counts.drafts} detail="Needs your approval"/><Metric label="Active jobs" value={counts.active} detail="Queued or scheduled"/><Metric label="Published" value={counts.uploaded} detail="Confirmed by YouTube"/><Metric label="Needs attention" value={counts.failed} detail="Retryable failures" warning={counts.failed > 0}/></section>
  <section className="split"><div className="panel"><PanelTitle title="Recent drafts" action="View all" onClick={() => setView("drafts")}/>{drafts.slice(0,4).map((d: Draft) => <DraftRow key={d.id} draft={d} onClick={() => openDraft(d)}/>)}{!drafts.length && <Empty text="No drafts yet. Upload a video to begin."/>}</div><div className="panel"><PanelTitle title="Recent activity" action="View jobs" onClick={() => setView("schedule")}/>{jobs.slice(0,5).map((j: Job) => <div className="activity" key={j.id}><span className={`status-dot ${j.status}`}/><div><strong>{statusLabel[j.status] || j.status}</strong><small>{new Date(j.run_at).toLocaleString()}</small></div><b>{j.progress}%</b></div>)}{!jobs.length && <Empty text="Job activity will appear here."/>}</div></section>
</>; }

function Metric({ label, value, detail, warning }: any) { return <div className={`metric ${warning ? "warning" : ""}`}><small>{label}</small><strong>{value}</strong><span>{detail}</span></div>; }
function PanelTitle({ title, action, onClick }: any) { return <div className="panel-title"><h3>{title}</h3><button onClick={onClick}>{action} →</button></div>; }
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div>; }
function DraftRow({ draft, onClick }: { draft: Draft; onClick: () => void }) { return <button className="draft-row" onClick={onClick}><span className="video-thumb"><FileVideo/></span><div><strong>{draft.title || draft.filename}</strong><small>{draft.filename} · {(draft.file_size / 1048576).toFixed(1)} MB</small></div><span className={`pill ${draft.status}`}>{statusLabel[draft.status] || draft.status}</span></button>; }

function UploadPanel({ upload, busy }: { upload: (files: File[]) => void; busy: string }) { const [drag, setDrag] = useState(false); return <section className="panel upload-panel"><div className="upload-copy"><span><Upload/></span><h2>Bring in your next videos</h2><p>MP4, MOV, M4V, WebM, MKV or AVI. Each file becomes a durable draft; exact duplicates are stopped.</p></div><label className={drag ? "dropzone drag" : "dropzone"} onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); const files=Array.from(e.dataTransfer.files); if(files.length) upload(files); }}><input multiple type="file" accept="video/mp4,video/quicktime,video/webm,.mkv,.avi,.m4v" onChange={e => { const files=Array.from(e.target.files || []); if(files.length) upload(files); }}/>{busy === "upload" ? <Loader2 className="spin"/> : <Upload/>}<strong>{busy === "upload" ? "Saving and checking videos…" : "Drop one or more videos here"}</strong><span>or click to choose files</span></label></section>; }

function DraftList({ drafts, open }: { drafts: Draft[]; open: (d: Draft) => void }) { return <section className="panel"><PanelTitle title={`${drafts.length} video drafts`} action="" onClick={() => {}}/>{drafts.map(d => <DraftRow key={d.id} draft={d} onClick={() => open(d)}/>)}{!drafts.length && <Empty text="Your draft library is empty."/>}</section>; }

function DraftEditor({ draft, setDraft, close, busy, act }: { draft: Draft; setDraft: (d: Draft) => void; close: () => void; busy: string; act: (n:string, f:()=>Promise<unknown>)=>void }) {
  const patch = (value: Partial<Draft>) => setDraft({ ...draft, ...value });
  const save = () => act("save", async () => setDraft((await api.updateDraft(draft.id, { title: draft.title, description: draft.description, tags: draft.tags, privacy_status: draft.privacy_status, category_id: draft.category_id, scheduled_at: draft.scheduled_at })).draft));
  return <div className="editor"><button className="back" onClick={close}>← Back to drafts</button><div className="editor-head"><div><span className={`pill ${draft.status}`}>{statusLabel[draft.status]}</span><h2>{draft.title || draft.filename}</h2><p>{draft.filename} · metadata: {draft.metadata_source}{draft.manually_edited ? " + manual edits" : ""}</p></div><button className="primary" disabled={!!busy} onClick={save}>{busy === "save" ? <Loader2 className="spin"/> : <Check/>} Save draft</button></div>
    <div className="editor-grid"><section className="panel form-panel"><h3>Video details</h3><label>Title <small>{draft.title.length}/100</small><input value={draft.title} maxLength={100} onChange={e => patch({ title: e.target.value })}/></label><label>Description <small>{draft.description.length}/5000</small><textarea rows={9} value={draft.description} maxLength={5000} onChange={e => patch({ description: e.target.value })}/></label><label>Tags<input value={draft.tags.join(", ")} onChange={e => patch({ tags: e.target.value.split(",").map(v => v.trim()).filter(Boolean) })}/></label><div className="form-row"><label>Privacy<select value={draft.privacy_status} onChange={e => patch({ privacy_status: e.target.value as Draft["privacy_status"] })}><option>private</option><option>unlisted</option><option>public</option></select></label><label>Category ID<input value={draft.category_id} onChange={e => patch({ category_id: e.target.value })}/></label></div></section>
      <aside className="tools"><section className="panel"><h3><Sparkles/> Automation</h3><ToolButton busy={busy === "metadata"} onClick={() => act("metadata", () => api.generateMetadata(draft.id))} title="Generate metadata" note={checksText(draft.metadata_source === "ai", "Uses AI when configured; safe fallback otherwise")}/><ToolButton busy={busy === "transcript"} onClick={() => act("transcript", () => api.generateTranscript(draft.id))} title="Generate transcript" note={draft.transcript?.status || "Optional Whisper workflow"}/><ToolButton busy={busy === "thumbnails"} onClick={() => act("thumbnails", () => api.generateThumbnails(draft.id))} title="Create thumbnails" note={`${draft.thumbnails?.length || 0} candidates`}/></section><section className="panel publish-card"><h3><Clock/> Publishing</h3><label>Schedule time (optional)<input type="datetime-local" value={draft.scheduled_at?.slice(0,16) || ""} onChange={e => patch({ scheduled_at: e.target.value ? new Date(e.target.value).toISOString() : null })}/></label><button className="primary full" disabled={!!busy || draft.status === "uploaded"} onClick={() => act("publish", () => api.createJob(draft.id, draft.scheduled_at || undefined))}>{draft.scheduled_at ? "Schedule upload" : "Queue for upload"}</button><small>The worker performs the real API call. Success appears only after YouTube returns a video ID.</small></section></aside>
    </div>{draft.transcript && <section className="panel transcript"><h3>Transcript</h3><textarea rows={8} value={draft.transcript.text} onChange={e => setDraft({ ...draft, transcript: { ...draft.transcript!, text: e.target.value } })}/><button onClick={() => act("save-transcript", () => api.saveTranscript(draft.id, draft.transcript!.text))}>Save transcript</button></section>}
    {!!draft.thumbnails?.length && <section className="panel"><h3>Thumbnail candidates</h3><div className="thumbnail-grid">{draft.thumbnails.map(t => <button key={t.id} className={t.selected ? "selected" : ""} onClick={() => act("select-thumb", () => api.selectThumbnail(draft.id, t.id))}><img src={`${api.url.replace(/\/api$/, "")}${t.url}`} alt={t.source}/><span>{t.selected ? "Selected" : t.source}</span></button>)}</div></section>}
  </div>;
}
function checksText(ok:boolean, text:string){ return ok ? "AI-generated; review before publishing" : text; }
function ToolButton({ busy, onClick, title, note }: any) { return <button className="tool-button" onClick={onClick} disabled={busy}>{busy ? <Loader2 className="spin"/> : <Sparkles/>}<div><strong>{title}</strong><small>{note}</small></div><span>→</span></button>; }

function Jobs({ jobs, drafts, busy, act }: any) { return <section className="panel"><PanelTitle title="Upload job queue" action="Refreshes automatically" onClick={()=>{}}/>{jobs.map((j: Job) => <div className="job-row" key={j.id}><span className={`status-dot ${j.status}`}/><div><strong>{drafts.find((d:Draft)=>d.id===j.draft_id)?.title || "Video upload"}</strong><small>{statusLabel[j.status] || j.status} · attempt {j.retry_count + 1} · {new Date(j.run_at).toLocaleString()}</small>{j.last_error && <p>{j.last_error}</p>}</div><div className="progress"><span style={{width:`${j.progress}%`}}/></div>{j.status === "failed" && <button disabled={!!busy} onClick={() => act("retry", () => api.retry(j.id))}>Retry</button>}{["queued","scheduled","retry_pending"].includes(j.status) && <button onClick={() => act("cancel", () => api.cancel(j.id))}>Cancel</button>}{j.status === "uploaded" && <Check/>}</div>)}{!jobs.length && <Empty text="No upload jobs yet."/>}</section>; }
function HistoryPanel({ drafts }: { drafts: Draft[] }) { const items=drafts.filter(d=>["uploaded","failed"].includes(d.status)); return <section className="panel"><h3>Real upload outcomes</h3>{items.map(d=><div className="history-row" key={d.id}><span className={`status-dot ${d.status}`}/><div><strong>{d.title}</strong><small>{new Date(d.created_at).toLocaleDateString()} · {statusLabel[d.status]}</small></div>{d.youtube_url && <a href={d.youtube_url} target="_blank" rel="noreferrer">Open on YouTube ↗</a>}</div>)}{!items.length&&<Empty text="Confirmed uploads and failures will appear here."/>}</section>; }
function SettingsPanel({ checks, auth, act }: any) { const connect=()=>act("connect", async()=>{ const {auth_url}=await api.login(); window.location.href=auth_url; }, false); return <div className="settings-grid"><section className="panel"><h3>YouTube connection</h3><div className="setting-state"><Video/><div><strong>{auth.authenticated ? auth.channel?.title : "No channel connected"}</strong><small>{auth.authenticated ? "OAuth credentials stored encrypted" : "Official Google OAuth is required to publish"}</small></div></div>{auth.authenticated ? <button onClick={()=>act("logout",()=>api.logout())}><LogOut/> Disconnect</button> : <button className="primary" onClick={connect}><Video/> Connect with Google</button>}</section><section className="panel"><h3>Service readiness</h3>{Object.entries(checks).map(([name, ok])=><div className="check" key={name}>{ok?<Check/>:<AlertCircle/>}<span>{name.replace(/_/g, " ")}</span><b>{ok?"Ready":"Not configured"}</b></div>)}</section><section className="panel note"><h3>Operator safeguards</h3><p>Uploads run through the durable worker. A draft is never marked published until the YouTube API returns its video ID. Thumbnail and playlist post-processing failures stay visible without falsifying the video result.</p></section></div>; }
