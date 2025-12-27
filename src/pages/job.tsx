import {
  Card,
  CardBody,
  CardHeader,
  Divider,
  Input,
  Spinner,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
  Textarea
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  downloadRemoteDir,
  getConfig,
  jobFetchGpu,
  jobGetExitCode,
  jobTailLogs,
  vastDestroyInstance,
  vastListInstances,
  vastRunJob
} from "../lib/tauri-api";
import type { RunVastJobInput } from "../lib/tauri-api";
import type { GpuRow, RemoteJobMeta, VastInstance } from "../lib/types";

export function JobPage() {
  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig
  });
  const instQuery = useQuery({
    queryKey: ["vastInstances"],
    queryFn: vastListInstances,
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 1,
  });

  // Job spec (Vast)
  const [projectDir, setProjectDir] = useState("");
  const [command, setCommand] = useState("");
  const [workdir, setWorkdir] = useState<string>("");
  const [outputDir, setOutputDir] = useState<string>(""); // remote_output_dir or model_output_dir
  const [hfHome, setHfHome] = useState<string>("");
  const [includeData, setIncludeData] = useState(false);
  const [includeModels, setIncludeModels] = useState(false);
  const [includeDotenv, setIncludeDotenv] = useState(false);
  const [extraExcludes, setExtraExcludes] = useState<string>("");

  const [instanceId, setInstanceId] = useState<string>("");
  const [sync, setSync] = useState(true);

  const [meta, setMeta] = useState<RemoteJobMeta | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const [localDownloadDir, setLocalDownloadDir] = useState<string>("");
  const [autoDownload, setAutoDownload] = useState(true);
  const [autoDestroy, setAutoDestroy] = useState(true);
  const [autoStatus, setAutoStatus] = useState<string | null>(null);
  const autoTriggeredRef = useRef(false);

  const runMut = useMutation({
    mutationFn: (input: RunVastJobInput) => vastRunJob(input)
  });

  const selectedInstance = useMemo(() => {
    const id = Number(instanceId);
    if (!Number.isFinite(id)) return null;
    return (instQuery.data ?? []).find((x) => x.id === id) ?? null;
  }, [instanceId, instQuery.data]);

  const effectiveHfHome = useMemo(() => {
    if (hfHome.trim()) return hfHome.trim();
    return cfgQuery.data?.colab.hf_home ?? "";
  }, [hfHome, cfgQuery.data]);

  const exitQuery = useQuery({
    queryKey: ["jobExitCode", meta?.remote.job_dir ?? null],
    queryFn: async () => {
      if (!meta) return null;
      return await jobGetExitCode({ ssh: meta.ssh, jobDir: meta.remote.job_dir });
    },
    enabled: !!meta,
    refetchInterval: meta ? 3_000 : false
  });

  const logsQuery = useQuery({
    queryKey: ["jobLogs", meta?.remote.log_path ?? null],
    queryFn: async () => {
      if (!meta) return [];
      return await jobTailLogs({ ssh: meta.ssh, logPath: meta.remote.log_path, lines: 200 });
    },
    enabled: !!meta,
    refetchInterval: meta && exitQuery.data == null ? 2_000 : false
  });

  const gpuQuery = useQuery({
    queryKey: ["jobGpu", meta?.ssh.host ?? null, meta?.ssh.port ?? null],
    queryFn: async () => {
      if (!meta) return [];
      return await jobFetchGpu({ ssh: meta.ssh });
    },
    enabled: !!meta,
    refetchInterval: meta && exitQuery.data == null ? 5_000 : false
  });

  useEffect(() => {
    if (!meta) return;
    const exit = exitQuery.data;
    if (exit == null) return;
    if (autoTriggeredRef.current) return;
    autoTriggeredRef.current = true;

    (async () => {
      try {
        if (autoDownload) {
          const remoteDir = meta.remote.output_dir;
          if (!remoteDir) throw new Error("remote.output_dir is null");
          const localDir = localDownloadDir.trim();
          if (!localDir) throw new Error("local download dir is empty");
          setAutoStatus("Downloading outputs…");
          await downloadRemoteDir({ ssh: meta.ssh, remoteDir: remoteDir, localDir: localDir, delete: false });
        }
        if (autoDestroy) {
          const id = Number(instanceId);
          if (Number.isFinite(id)) {
            setAutoStatus("Destroying instance…");
            await vastDestroyInstance(id);
          }
        }
        setAutoStatus("Done");
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setAutoStatus(`Auto action failed: ${msg}`);
      }
    })();
  }, [autoDestroy, autoDownload, exitQuery.data, instanceId, localDownloadDir, meta]);

  async function onRun() {
    setRunError(null);
    setMeta(null);
    setAutoStatus(null);
    autoTriggeredRef.current = false;

    const id = Number(instanceId);
    if (!Number.isFinite(id) || id <= 0) {
      setRunError("Please select a valid instance id.");
      return;
    }

    try {
      const input: RunVastJobInput = {
        project_dir: projectDir.trim(),
        command: command.trim(),
        instance_id: id,
        workdir: workdir.trim() ? workdir.trim() : null,
        remote_output_dir: outputDir.trim() ? outputDir.trim() : null,
        hf_home: effectiveHfHome.trim() ? effectiveHfHome.trim() : null,
        sync,
        include_data: includeData,
        include_models: includeModels,
        include_dotenv: includeDotenv,
        extra_excludes: extraExcludes.trim() ? extraExcludes.trim() : null
      } as any;

      const out = await runMut.mutateAsync(input);
      setMeta(out);

      const jobName = out.remote.job_dir.split("/").slice(-1)[0] ?? "job";
      const defaultLocal = projectDir.trim() ? `${projectDir.trim()}/doppio-output/${jobName}` : `./doppio-output/${jobName}`;
      setLocalDownloadDir((prev) => (prev.trim() ? prev : defaultLocal));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setRunError(msg);
    }
  }

  function renderInstanceHint(inst: VastInstance | null) {
    if (!inst) return <div className="text-xs text-foreground/60">Select an instance.</div>;
    return (
      <div className="text-xs text-foreground/60">
        SSH: {inst.ssh_host && inst.ssh_port ? `${inst.ssh_host}:${inst.ssh_port}` : "-"} · GPU:{" "}
        {inst.gpu_name ? `${inst.num_gpus ?? ""} ${inst.gpu_name}` : "-"}
      </div>
    );
  }

  const logsText = useMemo(() => (logsQuery.data ?? []).join("\n"), [logsQuery.data]);
  const gpuRows = useMemo<GpuRow[]>(() => gpuQuery.data ?? [], [gpuQuery.data]);

  return (
    <div className="p-6">
      <Card>
        <CardHeader className="flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Run</div>
            <div className="text-sm text-foreground/70">上传项目 → tmux 启动训练 → 轮询日志/GPU → 完成后自动下载/销毁。</div>
          </div>
          <Button color="primary" isLoading={runMut.isPending} onPress={onRun}>
            Run on Vast
          </Button>
        </CardHeader>
        <Divider />
        <CardBody className="gap-6">
          {cfgQuery.isLoading ? (
            <div className="flex items-center gap-3 py-4">
              <Spinner size="sm" />
              <div className="text-sm text-foreground/70">Loading config…</div>
            </div>
          ) : null}

          <section className="grid gap-3">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <Input
                label="Project Dir"
                value={projectDir}
                onValueChange={setProjectDir}
                placeholder="/path/to/your/project"
                description="会自动排除 .git/node_modules/src-tauri/target 等；可通过 extra excludes 再排除。"
              />
              <Input
                label="Instance ID"
                value={instanceId}
                onValueChange={setInstanceId}
                placeholder="e.g. 123456"
                description="从 Vast.ai Instances 页面复制（需要实例处于可 SSH 状态）。"
              />
            </div>
            {renderInstanceHint(selectedInstance)}

            <Input
              label="Command"
              value={command}
              onValueChange={setCommand}
              placeholder="python train.py --config configs/xxx.yaml"
              description="会在远端用 bash -lc 执行，并通过 tee 写入 train.log。"
            />

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Input
                label="Workdir (optional)"
                value={workdir}
                onValueChange={setWorkdir}
                placeholder="."
                description="相对于项目根目录的子目录；留空=项目根目录。"
              />
              <Input
                label="Output dir (optional)"
                value={outputDir}
                onValueChange={setOutputDir}
                placeholder="outputs"
                description="远端输出目录（留空则 job_dir/output；支持绝对路径或相对 workdir）。"
              />
              <Input
                label="HF_HOME (optional)"
                value={hfHome}
                onValueChange={setHfHome}
                placeholder={cfgQuery.data?.colab.hf_home ?? "~/.cache/huggingface"}
                description="留空则使用 Settings → Colab 的 hf_home 或默认 ~/.cache/huggingface。"
              />
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <Switch isSelected={sync} onValueChange={setSync}>
                Sync project (upload & extract)
              </Switch>
              <Input
                label="Extra excludes (optional)"
                value={extraExcludes}
                onValueChange={setExtraExcludes}
                placeholder="checkpoints, wandb"
                description="逗号/换行分隔，作为打包排除前缀。"
              />
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Switch isSelected={includeData} onValueChange={setIncludeData}>
                Include data/
              </Switch>
              <Switch isSelected={includeModels} onValueChange={setIncludeModels}>
                Include models/
              </Switch>
              <Switch isSelected={includeDotenv} onValueChange={setIncludeDotenv}>
                Include .env (unsafe)
              </Switch>
            </div>

            <Divider />

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Input
                label="Local download dir"
                value={localDownloadDir}
                onValueChange={setLocalDownloadDir}
                placeholder="/path/to/save/outputs"
                description="用于下载远端 output dir。"
              />
              <Switch isSelected={autoDownload} onValueChange={setAutoDownload}>
                Auto download on finish
              </Switch>
              <Switch isSelected={autoDestroy} onValueChange={setAutoDestroy}>
                Auto destroy instance on finish
              </Switch>
            </div>
          </section>

          {(runError || meta) && (
            <section className="grid gap-3">
              <Divider />
              {runError ? <div className="text-sm text-danger">Run failed: {runError}</div> : null}
              {meta ? (
                <>
                  <div className="text-sm grid gap-1">
                    <div>
                      <span className="font-semibold">tmux session:</span>{" "}
                      <span className="font-mono">{meta.remote.tmux_session}</span>
                    </div>
                    <div>
                      <span className="font-semibold">job_dir:</span>{" "}
                      <span className="font-mono text-xs">{meta.remote.job_dir}</span>
                    </div>
                    <div>
                      <span className="font-semibold">workdir:</span>{" "}
                      <span className="font-mono text-xs">{meta.remote.workdir}</span>
                    </div>
                    <div>
                      <span className="font-semibold">log:</span>{" "}
                      <span className="font-mono text-xs">{meta.remote.log_path}</span>
                    </div>
                    <div>
                      <span className="font-semibold">output_dir:</span>{" "}
                      <span className="font-mono text-xs">{meta.remote.output_dir ?? "-"}</span>
                    </div>
                    <div>
                      <span className="font-semibold">meta:</span>{" "}
                      <span className="font-mono text-xs">{meta.local_meta_path}</span>
                    </div>
                    <div>
                      <span className="font-semibold">exit code:</span>{" "}
                      {exitQuery.isLoading ? (
                        "…"
                      ) : exitQuery.data == null ? (
                        <span className="text-warning">running</span>
                      ) : (
                        exitQuery.data
                      )}
                    </div>
                    {autoStatus ? <div className="text-xs text-foreground/60">Auto: {autoStatus}</div> : null}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="flat"
                      isDisabled={!meta.remote.output_dir || !localDownloadDir.trim()}
                      onPress={async () => {
                        if (!meta.remote.output_dir) return;
                        await downloadRemoteDir({
                          ssh: meta.ssh,
                          remoteDir: meta.remote.output_dir,
                          localDir: localDownloadDir.trim(),
                          delete: false
                        });
                      }}
                    >
                      Download outputs
                    </Button>
                    <Button
                      color="danger"
                      variant="flat"
                      onPress={async () => {
                        const id = Number(instanceId);
                        if (!Number.isFinite(id)) return;
                        if (!confirm(`Destroy instance ${id}?`)) return;
                        await vastDestroyInstance(id);
                      }}
                    >
                      Destroy instance
                    </Button>
                    <Button variant="flat" onPress={() => logsQuery.refetch()}>
                      Refresh logs
                    </Button>
                    <Button variant="flat" onPress={() => gpuQuery.refetch()}>
                      Refresh GPU
                    </Button>
                  </div>

                  <Divider />

                  <div className="grid gap-3">
                    <div className="text-sm font-semibold">GPU</div>
                    <Table removeWrapper aria-label="GPU table">
                      <TableHeader>
                        <TableColumn>Index</TableColumn>
                        <TableColumn>Name</TableColumn>
                        <TableColumn>Util</TableColumn>
                        <TableColumn>Mem</TableColumn>
                        <TableColumn>Temp</TableColumn>
                        <TableColumn>Power</TableColumn>
                      </TableHeader>
                      <TableBody emptyContent="No GPU data">
                        {gpuRows.map((r) => (
                          <TableRow key={`${r.index}-${r.name}`}>
                            <TableCell className="font-mono text-xs">{r.index}</TableCell>
                            <TableCell className="text-sm">{r.name}</TableCell>
                            <TableCell className="text-sm">{r.util_gpu}%</TableCell>
                            <TableCell className="text-sm">
                              {r.mem_used}/{r.mem_total} MiB ({r.util_mem}%)
                            </TableCell>
                            <TableCell className="text-sm">{r.temp}°C</TableCell>
                            <TableCell className="text-sm">{r.power} W</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>

                  <Divider />

                  <div className="grid gap-3">
                    <div className="text-sm font-semibold">Logs (tail -n 200)</div>
                    <Textarea value={logsText} minRows={12} readOnly classNames={{ input: "font-mono text-xs" }} />
                  </div>
                </>
              ) : null}
            </section>
          )}
        </CardBody>
      </Card>
    </div>
  );
}


