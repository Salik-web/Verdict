import { readFile } from "node:fs/promises";
import path from "node:path";
import type { AppConfig } from "./config.js";

/**
 * Safe reads of pipeline-generated asset content from disk.
 *
 * `content_ref` is written by the pipeline as `artifacts/{accountId}/{assetId}.{ext}`
 * (see services/pipeline execution runner). We NEVER trust it blindly: the ref
 * must match that exact shape, its account/asset segments must equal the caller's
 * (so one tenant can't read another's file, and no path traversal escapes the
 * artifacts root). The HTML is already nh3-sanitized server-side; the browser
 * additionally renders it in a locked-down sandboxed iframe.
 */

export function artifactsBase(config: AppConfig): string {
  return path.resolve(process.cwd(), config.PIPELINE_ARTIFACTS_DIR);
}

const REF_SHAPE = /^artifacts\/([0-9a-fA-F-]+)\/([0-9a-fA-F-]+)\.([a-z0-9]+)$/;

export function resolveArtifactPath(
  config: AppConfig,
  accountId: string,
  assetId: string,
  contentRef: string,
): string {
  const norm = contentRef.replace(/\\/g, "/");
  const m = REF_SHAPE.exec(norm);
  if (!m) throw new Error(`unexpected content_ref shape: ${contentRef}`);
  const [, refAccount, refAsset] = m;
  if (refAccount !== accountId) throw new Error("content_ref tenant mismatch");
  if (refAsset !== assetId) throw new Error("content_ref asset mismatch");

  const base = artifactsBase(config);
  const artifactsRoot = path.join(base, "artifacts");
  const full = path.resolve(base, norm);
  if (full !== artifactsRoot && !full.startsWith(artifactsRoot + path.sep)) {
    throw new Error("content_ref escapes artifacts root");
  }
  return full;
}

export async function readArtifact(
  config: AppConfig,
  accountId: string,
  assetId: string,
  contentRef: string,
): Promise<string> {
  return readFile(resolveArtifactPath(config, accountId, assetId, contentRef), "utf8");
}
