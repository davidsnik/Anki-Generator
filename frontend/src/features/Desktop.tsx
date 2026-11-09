import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, ExternalLink, FolderOpen, Monitor, RefreshCw } from 'lucide-react';
import { desktopBridge, desktopRoute } from '../services/desktop';
import type { DesktopInfo } from '../services/desktop';
import { ErrorPanel, SectionHead, useToast } from '../components/UI';
export function DesktopEvents() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const toast = useToast();
  useEffect(() => {
    const bridge = desktopBridge();
    if (!bridge) return;
    const subscriptions = [
      bridge.onNavigate((route) => {
        if (desktopRoute(route)) navigate(route);
      }),
      bridge.onState((info) => {
        client.setQueryData(['desktop', 'info'], info);
      }),
      bridge.onDownload((file) => {
        client.setQueryData<DesktopInfo>(['desktop', 'info'], (previous) =>
          previous ? { ...previous, last_download: file } : previous,
        );
        void client.invalidateQueries({ queryKey: ['desktop', 'info'] });
        toast(`${file.filename} saved. Open it or show its folder from desktop settings.`);
      }),
    ];
    return () => subscriptions.forEach((stop) => stop());
  }, [navigate, client, toast]);
  return null;
}
export function DesktopPanel() {
  const bridge = desktopBridge();
  const [technical, setTechnical] = useState(false);
  const toast = useToast();
  const info = useQuery({
    queryKey: ['desktop', 'info'],
    queryFn: () => bridge!.info(),
    enabled: !!bridge,
    refetchInterval: 15000,
  });
  const diagnostics = useQuery({
    queryKey: ['desktop', 'diagnostics'],
    queryFn: () => bridge!.diagnostics(),
    enabled: !!bridge && technical,
  });
  const action = useMutation({
    mutationFn: (operation: () => Promise<unknown>) => operation(),
    onSuccess: (result) => {
      if (result && typeof result === 'object' && 'saved' in result && result.saved)
        toast('Safe application diagnostics saved.');
    },
  });
  if (!bridge) return null;
  const data = info.data;
  return (
    <section className="panel desktop-settings" id="desktop-diagnostics">
      <SectionHead title="Desktop workspace" action={<Monitor size={20} />}>
        Your desktop application manages its private processing service automatically.
      </SectionHead>
      {info.error && <ErrorPanel error={info.error} />}
      {data && (
        <>
          <dl className="desktop-information">
            <div>
              <dt>Application</dt>
              <dd>Anki Generator {data.application_version}</dd>
            </div>
            <div>
              <dt>Backend</dt>
              <dd>
                {data.backend_version || 'Starting'} · {data.status}
              </dd>
            </div>
            <div>
              <dt>Course data</dt>
              <dd>
                <code>{data.data_directory}</code>
              </dd>
            </div>
            <div>
              <dt>State & logs</dt>
              <dd>
                <code>{data.state_directory}</code>
              </dd>
            </div>
          </dl>
          <p className="field-help">
            Moving or updating the executable leaves this workspace in place. API keys stay in
            backend memory or an available secure credential store.
          </p>
        </>
      )}
      <div className="desktop-directory-actions">
        <button
          className="button small"
          disabled={action.isPending}
          onClick={() => action.mutate(() => bridge.openDirectory('data'))}
        >
          <FolderOpen size={14} />
          Open data folder
        </button>
        <button
          className="button small"
          disabled={action.isPending}
          onClick={() => action.mutate(() => bridge.openDirectory('downloads'))}
        >
          <FolderOpen size={14} />
          Open downloads
        </button>
        <button
          className="button small"
          disabled={action.isPending}
          onClick={() => action.mutate(() => bridge.openDirectory('logs'))}
        >
          <FolderOpen size={14} />
          Open logs
        </button>
      </div>
      {data?.last_download && (
        <div className="desktop-saved-file">
          <strong>Last saved file</strong>
          <span>{data.last_download.filename}</span>
          <div className="inline-actions wrap">
            <button
              className="button small"
              disabled={action.isPending}
              onClick={() =>
                action.mutate(() => bridge.openDownload(data.last_download!.id, 'file'))
              }
            >
              <ExternalLink size={13} />
              Open file
            </button>
            <button
              className="button small"
              disabled={action.isPending}
              onClick={() =>
                action.mutate(() => bridge.openDownload(data.last_download!.id, 'folder'))
              }
            >
              <FolderOpen size={13} />
              Show in folder
            </button>
          </div>
        </div>
      )}
      <details>
        <summary>Bring courses from the browser version</summary>
        <p className="field-help">
          In the existing browser workspace, create a data backup from Settings. Close that
          application, then use <strong>Data & storage → Validate & restore backup</strong> here.
          Review the validation report and confirm the restore. API keys are excluded; configure
          your key again if needed. The desktop application never silently overwrites or copies an
          existing workspace.
        </p>
      </details>
      <hr />
      <div className="desktop-directory-actions">
        <button
          className="button small"
          disabled={action.isPending}
          onClick={() => action.mutate(() => bridge.exportDiagnostics())}
        >
          <Download size={14} />
          Export desktop diagnostics
        </button>
        <button
          className="button small"
          disabled={action.isPending}
          onClick={() => action.mutate(() => bridge.restartBackend())}
        >
          <RefreshCw size={14} />
          Restart processing service
        </button>
      </div>
      <p className="field-help">
        Restarting preserves saved data. Active work needs a checkpoint confirmation; in-flight
        operations may take time to finish. Diagnostics exclude API keys and document contents.
      </p>
      <button className="text-link" onClick={() => setTechnical((value) => !value)}>
        {technical ? 'Hide' : 'View'} desktop runtime details
      </button>
      {technical && (
        <div className="desktop-runtime-details">
          {diagnostics.isPending ? (
            <p className="field-help">Reading runtime details…</p>
          ) : diagnostics.error ? (
            <ErrorPanel error={diagnostics.error} />
          ) : (
            <pre>{JSON.stringify(diagnostics.data, null, 2)}</pre>
          )}
        </div>
      )}
      {action.error && <ErrorPanel error={action.error} />}
    </section>
  );
}
