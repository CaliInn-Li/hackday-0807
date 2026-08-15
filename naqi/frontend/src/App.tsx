import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiClient, ApiError, createSessionTokenStore, getStoredApiBase, hasStoredApiKey, setStoredApiBase } from "./api";
import type { AnimationAsset, CharacterAsset, ConnectionState, Job, MotionAsset } from "./api/types";
import { AppShell, type PageId } from "./components/AppShell";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { AnimationsView } from "./views/AnimationsView";
import { CharactersView } from "./views/CharactersView";
import { JobsView } from "./views/JobsView";
import { MotionsView } from "./views/MotionsView";
import { OverviewView } from "./views/OverviewView";
import { sortNewestFirst } from "./lib/format";

const fallbackBase = import.meta.env.VITE_NAQI_API_BASE || "http://localhost:18080";

interface ResourceResult<T> {
  data: T;
  unsupported: boolean;
  error?: string;
}

interface WorkspaceData {
  characters: CharacterAsset[];
  motions: MotionAsset[];
  animations: AnimationAsset[];
  jobs: Job[];
  unsupported: {
    characters: boolean;
    motions: boolean;
    animations: boolean;
    jobs: boolean;
  };
  errors: string[];
}

const emptyData: WorkspaceData = {
  characters: [],
  motions: [],
  animations: [],
  jobs: [],
  unsupported: { characters: false, motions: false, animations: false, jobs: false },
  errors: [],
};

export default function App(): JSX.Element {
  const [page, setPage] = useState<PageId>("overview");
  const [baseUrl, setBaseUrl] = useState(() => getStoredApiBase() || fallbackBase);
  const [tokenVersion, setTokenVersion] = useState(0);
  const tokenStore = useMemo(() => createSessionTokenStore(), []);
  const api = useMemo(() => new ApiClient({ baseUrl, tokenStore }), [baseUrl, tokenStore, tokenVersion]);
  const [settingsOpen, setSettingsOpen] = useState(() => !hasStoredApiKey());
  const [connectionState, setConnectionState] = useState<ConnectionState>("unknown");
  const [connectionMessage, setConnectionMessage] = useState<string>();
  const [data, setData] = useState<WorkspaceData>(emptyData);
  const [loading, setLoading] = useState(false);
  const loadController = useRef<AbortController | null>(null);

  const testConnection = useCallback(async (): Promise<void> => {
    setConnectionState("checking");
    setConnectionMessage(undefined);
    try {
      await api.healthLive();
      setConnectionState("connected");
      setConnectionMessage("health/live 正常");
    } catch (caught: unknown) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        setConnectionState("unauthorized");
        setConnectionMessage("请检查 Bearer Key");
        return;
      }
      if (caught instanceof ApiError && caught.status === 404) {
        try {
          await api.listJobs();
          setConnectionState("connected");
          setConnectionMessage("服务可达，health/live 尚未实现");
          return;
        } catch (fallbackError: unknown) {
          if (fallbackError instanceof ApiError && fallbackError.status === 404) {
            setConnectionState("connected");
            setConnectionMessage("服务可达，但接口版本待对齐");
            return;
          }
          if (fallbackError instanceof ApiError && (fallbackError.status === 401 || fallbackError.status === 403)) {
            setConnectionState("unauthorized");
            setConnectionMessage("请检查 Bearer Key");
            return;
          }
        }
      }
      setConnectionState("offline");
      setConnectionMessage(caught instanceof Error ? caught.message : "请求失败");
    }
  }, [api]);

  const loadData = useCallback(async (): Promise<void> => {
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    setLoading(true);
    const safe = async <T,>(loader: () => Promise<T>, empty: T): Promise<ResourceResult<T>> => {
      try {
        return { data: await loader(), unsupported: false };
      } catch (caught: unknown) {
        if (controller.signal.aborted) throw caught;
        if (caught instanceof ApiError && caught.status === 404) return { data: empty, unsupported: true };
        return { data: empty, unsupported: false, error: caught instanceof Error ? caught.message : "请求失败" };
      }
    };

    try {
      const [characters, motions, animations, jobs] = await Promise.all([
        safe(() => api.listCharacters({ signal: controller.signal }), [] as CharacterAsset[]),
        safe(() => api.listMotions({ signal: controller.signal }), [] as MotionAsset[]),
        safe(() => api.listAnimations({ signal: controller.signal }), [] as AnimationAsset[]),
        safe(() => api.listJobs({ signal: controller.signal }), [] as Job[]),
      ]);
      if (controller.signal.aborted) return;
      setData({
        characters: sortNewestFirst(characters.data),
        motions: sortNewestFirst(motions.data),
        animations: sortNewestFirst(animations.data),
        jobs: sortNewestFirst(jobs.data),
        unsupported: {
          characters: characters.unsupported,
          motions: motions.unsupported,
          animations: animations.unsupported,
          jobs: jobs.unsupported,
        },
        errors: [characters.error, motions.error, animations.error, jobs.error].filter((item): item is string => Boolean(item)),
      });
    } catch (caught: unknown) {
      if (!controller.signal.aborted) {
        setData((current) => ({ ...current, errors: [caught instanceof Error ? caught.message : "读取资产失败"] }));
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void testConnection();
    void loadData();
    return () => loadController.current?.abort();
  }, [loadData, testConnection]);

  async function handleUploadCharacter(file: File): Promise<void> {
    await api.uploadCharacter(file);
    await loadData();
  }

  async function handleUploadMotion(file: File, cameraMode: string): Promise<void> {
    await api.uploadMotion(file, { cameraMode });
    await loadData();
  }

  async function handleCreateAnimation(characterId: string, motionId: string): Promise<void> {
    await api.createAnimation({ characterId, motionId });
    await loadData();
    setPage("jobs");
  }

  function saveConnection(nextBaseUrl: string, token?: string): void {
    const next = nextBaseUrl.trim() || fallbackBase;
    setStoredApiBase(next);
    setBaseUrl(next);
    if (token) api.setToken(token);
    setTokenVersion((version) => version + 1);
    setSettingsOpen(false);
  }

  function clearToken(): void {
    api.clearToken();
    setTokenVersion((version) => version + 1);
    setConnectionState("unknown");
    setConnectionMessage("Key 已清除");
  }

  function renderPage(): JSX.Element {
    switch (page) {
      case "characters":
        return <CharactersView api={api} characters={data.characters} loading={loading} unsupported={data.unsupported.characters} onUpload={handleUploadCharacter} />;
      case "motions":
        return <MotionsView api={api} motions={data.motions} loading={loading} unsupported={data.unsupported.motions} onUpload={handleUploadMotion} />;
      case "animations":
        return <AnimationsView api={api} animations={data.animations} characters={data.characters} motions={data.motions} loading={loading} unsupported={data.unsupported.animations} onCreate={handleCreateAnimation} />;
      case "jobs":
        return <JobsView api={api} jobs={data.jobs} loading={loading} unsupported={data.unsupported.jobs} onRefresh={() => void loadData()} />;
      case "overview":
      default:
        return <OverviewView jobs={data.jobs} loading={loading} onOpenJobs={() => setPage("jobs")} onOpenSettings={() => setSettingsOpen(true)} />;
    }
  }

  return (
    <>
      <AppShell page={page} onPageChange={setPage} onSettings={() => setSettingsOpen(true)} connectionState={connectionState} hasToken={Boolean(api.token)}>
        {data.errors.length > 0 ? <div className="notice notice-warning"><strong>部分接口读取失败：</strong> {data.errors[0]}</div> : null}
        {renderPage()}
      </AppShell>
      <ConnectionPanel
        open={settingsOpen}
        api={api}
        baseUrl={baseUrl}
        hasToken={Boolean(api.token)}
        connectionState={connectionState}
        connectionMessage={connectionMessage}
        onClose={() => setSettingsOpen(false)}
        onSave={saveConnection}
        onClearToken={clearToken}
        onTest={() => void testConnection()}
      />
    </>
  );
}
