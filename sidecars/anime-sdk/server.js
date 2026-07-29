import { createServer } from "node:http";
import {
  createReadStream,
  createWriteStream,
  mkdirSync,
  rmSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pipeline } from "node:stream/promises";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";

import {
  AnimeParadiseProvider,
  AnikotoProvider,
  GogoanimeProvider,
  HttpClient,
  MegaPlayProvider,
  downloadVideo,
} from "anime-sdk";


const PORT = Number(process.env.PORT ?? "8080");
const SDK_VERSION = "1.1.0";
const MAX_BODY_BYTES = 1024 * 1024;
const DEFAULT_USER_AGENT =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const IEND_MAGIC = Buffer.from([0x49, 0x45, 0x4e, 0x44]);
const configuredSegmentConcurrency = Number(
  process.env.ANIME_SDK_SEGMENT_CONCURRENCY ?? "3",
);
const SEGMENT_CONCURRENCY =
  Number.isInteger(configuredSegmentConcurrency) &&
  configuredSegmentConcurrency >= 1 &&
  configuredSegmentConcurrency <= 8
    ? configuredSegmentConcurrency
    : 3;

const httpClient = new HttpClient({ timeoutMs: 30_000 });
const providerFactories = {
  animeparadise: () => new AnimeParadiseProvider(httpClient),
  gogoanime: () => new GogoanimeProvider(httpClient),
  anikoto: () => new AnikotoProvider(httpClient),
  megaplay: () => new MegaPlayProvider(httpClient),
};
const enabledProviderIds = new Set(
  (process.env.ANIME_SDK_PROVIDERS ??
    "animeparadise,gogoanime,anikoto,megaplay")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean),
);
const providers = new Map(
  [...enabledProviderIds]
    .filter((providerId) => providerFactories[providerId])
    .map((providerId) => [providerId, providerFactories[providerId]()]),
);
const progressStates = new Map();


function setProgress(requestId, backend, phase, percent, detail) {
  const progress = {
    request_id: requestId,
    backend,
    phase,
    percent: Math.max(0, Math.min(100, Math.round(percent))),
    detail,
    updated_at: new Date().toISOString(),
  };
  progressStates.set(requestId, progress);
  return progress;
}


function scheduleProgressCleanup(requestId) {
  const timer = setTimeout(() => progressStates.delete(requestId), 5 * 60 * 1000);
  timer.unref();
}


function reportSdkProgress(report, info) {
  const detail = String(info.detail ?? "");
  const segment = detail.match(/segment\s+(\d+)\s*\/\s*(\d+)/i);
  if (segment) {
    const current = Number(segment[1]);
    const total = Number(segment[2]);
    report("downloading", total ? (current / total) * 100 : 0, detail);
    return;
  }
  const phases = {
    resolving: ["resolving", 0, "Resolving stream"],
    downloading: ["downloading", 0, detail || "Starting download"],
    muxing: ["muxing", 100, detail || "Preparing MP4"],
    complete: ["prepared", 100, "Download prepared"],
  };
  const mapped = phases[info.phase];
  if (mapped) report(...mapped);
}


class SidecarError extends Error {
  constructor(code, status, detail, { retryable = false, retryAfter = null } = {}) {
    super(detail);
    this.code = code;
    this.status = status;
    this.retryable = retryable;
    this.retryAfter = retryAfter;
  }
}


function sendJson(response, status, payload, contentType = "application/json") {
  const body = Buffer.from(JSON.stringify(payload));
  response.writeHead(status, {
    "content-type": `${contentType}; charset=utf-8`,
    "content-length": body.length,
  });
  response.end(body);
}


function sendProblem(response, error) {
  const problem =
    error instanceof SidecarError
      ? error
      : classifyProviderError(error);
  sendJson(
    response,
    problem.status,
    {
      type: `https://meido.local/problems/${problem.code}`,
      title: problem.code.replaceAll("_", " "),
      status: problem.status,
      code: problem.code,
      detail: problem.message,
      retryable: problem.retryable,
      retry_after: problem.retryAfter,
    },
    "application/problem+json",
  );
}


function classifyProviderError(error) {
  const detail = String(error?.message ?? error).slice(0, 1000);
  const normalized = detail.toLowerCase();
  if (
    normalized.includes("captcha") ||
    normalized.includes("challenge") ||
    normalized.includes("cf-mitigated") ||
    normalized.includes("http 403") ||
    normalized.includes(" 403 ")
  ) {
    return new SidecarError("challenged", 503, detail, {
      retryable: true,
      retryAfter: 900,
    });
  }
  if (normalized.includes("429") || normalized.includes("rate limit")) {
    return new SidecarError("rate_limited", 503, detail, {
      retryable: true,
      retryAfter: 300,
    });
  }
  if (
    normalized.includes("timeout") ||
    normalized.includes("timed out") ||
    normalized.includes("fetch failed") ||
    normalized.includes("econn") ||
    normalized.includes("enotfound") ||
    normalized.includes("http 5")
  ) {
    return new SidecarError("temporary", 503, detail, { retryable: true });
  }
  return new SidecarError("temporary", 503, detail, { retryable: true });
}


async function readJson(request) {
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    total += chunk.length;
    if (total > MAX_BODY_BYTES) {
      throw new SidecarError("invalid_request", 413, "request body is too large");
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new SidecarError("invalid_request", 400, "request body must be JSON");
  }
}


function requireInteger(value, name, minimum = 1) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum) {
    throw new SidecarError(
      "invalid_request",
      400,
      `${name} must be an integer greater than or equal to ${minimum}`,
    );
  }
  return parsed;
}


function normalizeTitle(value) {
  return String(value)
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}


function editDistance(left, right) {
  const leftCharacters = Array.from(left);
  const rightCharacters = Array.from(right);
  let previous = rightCharacters.map((_, index) => index + 1);
  previous.unshift(0);

  for (const [leftIndex, leftCharacter] of leftCharacters.entries()) {
    const current = [leftIndex + 1];
    for (const [rightIndex, rightCharacter] of rightCharacters.entries()) {
      current.push(
        Math.min(
          current[rightIndex] + 1,
          previous[rightIndex + 1] + 1,
          previous[rightIndex] + (leftCharacter === rightCharacter ? 0 : 1),
        ),
      );
    }
    previous = current;
  }
  return previous.at(-1);
}


function selectExactTitle(results, title, season) {
  const requested =
    season > 1 ? `${title} season ${season}` : title;
  const requestedNormalized = normalizeTitle(requested);
  const titleNormalized = normalizeTitle(title);
  const exact = results.find(
    (result) => normalizeTitle(result.title) === requestedNormalized,
  );
  if (exact) return exact;
  if (season === 1) {
    const baseExact = results.filter(
      (result) => normalizeTitle(result.title) === titleNormalized,
    );
    if (baseExact.length === 1) return baseExact[0];
  }

  const fuzzyTarget =
    season === 1 ? titleNormalized : requestedNormalized;
  const maximumDistance = fuzzyTarget.length >= 20 ? 2 : 1;
  const candidates = results
    .map((result) => ({
      result,
      distance: editDistance(
        normalizeTitle(result.title),
        fuzzyTarget,
      ),
    }))
    .sort((left, right) => left.distance - right.distance);
  const closestDistance = candidates[0]?.distance;
  const closest = candidates.filter(
    (candidate) => candidate.distance === closestDistance,
  );
  if (
    closestDistance != null &&
    closestDistance <= maximumDistance &&
    closest.length === 1
  ) {
    return closest[0].result;
  }

  throw new SidecarError(
    "not_found",
    404,
    `no unambiguous exact match for ${requested}`,
  );
}


async function findTitle(provider, title, season, report) {
  const query = season > 1 ? `${title} Season ${season}` : title;
  const resultsById = new Map();
  const addResults = (results) => {
    for (const result of results) resultsById.set(result.id, result);
  };

  addResults(await provider.search(query));
  try {
    return selectExactTitle([...resultsById.values()], title, season);
  } catch (error) {
    if (!(error instanceof SidecarError) || error.code !== "not_found") {
      throw error;
    }
  }

  const fallbackTerms = normalizeTitle(title)
    .split(" ")
    .filter((term) => term.length >= 4)
    .slice(0, 3);
  for (const term of fallbackTerms) {
    report("searching", 0, `Trying broader title search: ${term}`);
    addResults(await provider.search(term));
    try {
      return selectExactTitle([...resultsById.values()], title, season);
    } catch (error) {
      if (!(error instanceof SidecarError) || error.code !== "not_found") {
        throw error;
      }
    }
  }

  throw new SidecarError(
    "not_found",
    404,
    `no unambiguous close match for ${query}`,
  );
}


function fetchHeaders(extra = {}) {
  return { "User-Agent": DEFAULT_USER_AGENT, ...extra };
}


function resolvePlaylistLines(content, baseUrl) {
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => new URL(line, baseUrl).toString());
}


function parseSegments(content, baseUrl) {
  const segments = [];
  let duration = 0;
  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (line.startsWith("#EXTINF:")) {
      duration = Number(line.match(/#EXTINF:([0-9.]+)/)?.[1] ?? 0);
    } else if (line && !line.startsWith("#")) {
      segments.push({
        url: new URL(line, baseUrl).toString(),
        duration,
      });
    }
  }
  return segments;
}


function stripPngWrapper(buffer) {
  if (!buffer.subarray(0, 8).equals(PNG_MAGIC)) return buffer;
  const marker = buffer.indexOf(IEND_MAGIC);
  const offset = marker + 8;
  return marker >= 0 && offset < buffer.length ? buffer.subarray(offset) : buffer;
}


async function fetchChecked(url, headers, label) {
  const response = await fetch(url, { headers: fetchHeaders(headers) });
  if (!response.ok) {
    const isCloudflareChallenge =
      response.headers.get("cf-mitigated") === "challenge" &&
      (response.headers.get("content-type") ?? "").includes("text/html");
    if (isCloudflareChallenge) {
      throw new SidecarError(
        "challenged",
        503,
        `${label} returned a Cloudflare challenge`,
        { retryable: true, retryAfter: 900 },
      );
    }
    if (response.status === 403) {
      throw new SidecarError(
        "challenged",
        503,
        `${label} returned HTTP 403`,
        { retryable: true, retryAfter: 900 },
      );
    }
    if (response.status === 429) {
      const retryAfter = Number(response.headers.get("retry-after")) || 300;
      throw new SidecarError(
        "rate_limited",
        503,
        `${label} returned HTTP 429`,
        { retryable: true, retryAfter },
      );
    }
    throw new SidecarError(
      response.status === 404 ? "not_found" : "temporary",
      response.status === 404 ? 404 : 503,
      `${label} returned HTTP ${response.status}`,
      { retryable: response.status !== 404 },
    );
  }
  return response;
}


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


async function fetchSegmentBytes(segment, headers) {
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetchChecked(
        segment.url,
        headers,
        "media segment",
      );
      return stripPngWrapper(
        Buffer.from(await response.arrayBuffer()),
      );
    } catch (error) {
      lastError = error;
      if (
        error instanceof SidecarError &&
        (
          !error.retryable ||
          error.code === "challenged" ||
          error.code === "rate_limited"
        )
      ) {
        throw error;
      }
      if (attempt < 3) await delay(attempt * 250);
    }
  }
  throw lastError;
}


function runFfmpeg(args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const child = spawn("ffmpeg", args, {
      stdio: ["ignore", "ignore", "pipe"],
    });
    const stderr = [];
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`ffmpeg exceeded ${timeoutMs}ms`));
    }, timeoutMs);
    child.stderr.on("data", (chunk) => {
      stderr.push(chunk);
      if (stderr.reduce((size, value) => size + value.length, 0) > 1024 * 1024) {
        stderr.shift();
      }
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) resolve();
      else {
        reject(
          new Error(
            `ffmpeg exited ${code}: ${Buffer.concat(stderr).toString("utf8").slice(-1000)}`,
          ),
        );
      }
    });
  });
}


async function downloadHls(
  stream,
  outputPath,
  sampleSeconds,
  report,
) {
  const headers = stream.headers ?? {};
  let playlistUrl = stream.sourceUrl;
  let response = await fetchChecked(playlistUrl, headers, "playlist");
  let playlist = await response.text();

  for (
    let hop = 0;
    hop < 2 && playlist.includes("#EXT-X-STREAM-INF");
    hop += 1
  ) {
    const variants = resolvePlaylistLines(playlist, playlistUrl);
    if (!variants.length) {
      throw new SidecarError(
        "temporary",
        503,
        "master playlist contains no variants",
        { retryable: true },
      );
    }
    playlistUrl = variants.at(-1);
    response = await fetchChecked(playlistUrl, headers, "variant playlist");
    playlist = await response.text();
  }

  const available = parseSegments(playlist, playlistUrl);
  const selected = [];
  if (sampleSeconds == null) {
    selected.push(...available);
  } else {
    let accumulated = 0;
    for (const segment of available) {
      selected.push(segment);
      accumulated += segment.duration;
      if (accumulated >= sampleSeconds + 2) break;
    }
  }
  if (!selected.length) {
    throw new SidecarError(
      "temporary",
      503,
      "media playlist contains no segments",
      { retryable: true },
    );
  }

  const transportPath = `${outputPath}.ts`;
  rmSync(transportPath, { force: true });
  const transportStream = createWriteStream(transportPath);
  try {
    let completed = 0;
    for (
      let offset = 0;
      offset < selected.length;
      offset += SEGMENT_CONCURRENCY
    ) {
      const batch = selected.slice(
        offset,
        offset + SEGMENT_CONCURRENCY,
      );
      const buffers = await Promise.all(
        batch.map((segment) => fetchSegmentBytes(segment, headers)),
      );
      for (const bytes of buffers) {
        if (!transportStream.write(bytes)) {
          await new Promise(
            (resolve) => transportStream.once("drain", resolve),
          );
        }
        completed += 1;
        report(
          "downloading",
          (completed / selected.length) * 100,
          `Segment ${completed}/${selected.length}`,
        );
      }
    }
  } finally {
    await new Promise((resolve, reject) => {
      transportStream.once("error", reject);
      transportStream.end(resolve);
    });
  }

  try {
    report(
      "muxing",
      100,
      sampleSeconds == null ? "Preparing MP4" : "Preparing sample MP4",
    );
    const ffmpegArguments = [
      "-y",
      "-hide_banner",
      "-loglevel",
      "error",
      "-i",
      transportPath,
    ];
    if (sampleSeconds != null) {
      ffmpegArguments.push("-t", String(sampleSeconds));
    }
    ffmpegArguments.push(
      "-c",
      "copy",
      "-movflags",
      "+faststart",
      outputPath,
    );
    await runFfmpeg(
      ffmpegArguments,
      sampleSeconds == null ? 20 * 60 * 1000 : 120_000,
    );
  } finally {
    rmSync(transportPath, { force: true });
  }
}


async function prepareDownload(payload, outputPath, report) {
  if (payload.contract_version !== 1) {
    throw new SidecarError(
      "invalid_request",
      400,
      "contract_version must be 1",
    );
  }
  const providerId = String(payload.backend ?? "").trim().toLowerCase();
  const provider = providers.get(providerId);
  if (!provider) {
    throw new SidecarError(
      "unsupported",
      422,
      `provider is not enabled: ${providerId || "<empty>"}`,
    );
  }
  const title = String(payload.title ?? "").trim();
  if (!title || title.length > 200) {
    throw new SidecarError(
      "invalid_request",
      400,
      "title must contain 1 to 200 characters",
    );
  }
  const season = requireInteger(payload.season, "season");
  const episodeNumber = requireInteger(payload.episode, "episode");
  const sampleSeconds =
    payload.sample_seconds == null
      ? null
      : requireInteger(payload.sample_seconds, "sample_seconds");
  if (sampleSeconds != null && sampleSeconds > 60) {
    throw new SidecarError(
      "invalid_request",
      400,
      "sample_seconds cannot exceed 60",
    );
  }
  const language =
    payload.language === "dub" ? "dub" : "sub";
  report("searching", 0, "Searching title");
  const selectedTitle = await findTitle(
    provider,
    title,
    season,
    report,
  );
  if (normalizeTitle(selectedTitle.title) !== normalizeTitle(title)) {
    report(
      "searching",
      100,
      `Matched title: ${selectedTitle.title}`,
    );
  }
  report("episodes", 0, "Loading episode list");
  const units = await provider.fetchContentUnits(selectedTitle.id);
  const unit = units.find(
    (candidate) => Number(candidate.number) === episodeNumber,
  );
  if (!unit) {
    throw new SidecarError(
      "not_found",
      404,
      `${selectedTitle.title} episode ${episodeNumber} is unavailable`,
    );
  }
  report("resolving", 0, "Resolving stream");
  const resolved = await provider.resolveStream(unit.id, language);
  if (resolved.type !== "video" || !resolved.streams.length) {
    throw new SidecarError(
      "not_found",
      404,
      `${selectedTitle.title} episode ${episodeNumber} has no video streams`,
    );
  }

  if (sampleSeconds != null) {
    let lastError = null;
    for (const stream of resolved.streams) {
      try {
        if (!stream.isHLS && !stream.sourceUrl.includes(".m3u8")) {
          throw new Error("sample mode currently requires HLS");
        }
        await downloadHls(
          stream,
          outputPath,
          sampleSeconds,
          report,
        );
        report("prepared", 100, "Sample prepared");
        return;
      } catch (error) {
        lastError = error;
        rmSync(outputPath, { force: true });
      }
    }
    throw lastError ?? new Error("every stream candidate failed");
  }

  let lastHlsError = null;
  const directStreams = [];
  for (const stream of resolved.streams) {
    if (stream.isHLS || stream.sourceUrl.includes(".m3u8")) {
      try {
        await downloadHls(stream, outputPath, null, report);
        report("prepared", 100, "Download prepared");
        return;
      } catch (error) {
        lastHlsError = error;
        rmSync(outputPath, { force: true });
      }
    } else {
      directStreams.push(stream);
    }
  }
  if (!directStreams.length) {
    throw lastHlsError ?? new Error("every HLS stream candidate failed");
  }

  await downloadVideo(directStreams, outputPath, {
    timeoutMs: 20 * 60 * 1000,
    onProgress: (info) => reportSdkProgress(report, info),
  });
}


async function handleDownload(request, response) {
  const payload = await readJson(request);
  const requestId = String(payload.request_id ?? "").trim();
  if (!requestId || requestId.length > 128) {
    throw new SidecarError(
      "invalid_request",
      400,
      "request_id must contain 1 to 128 characters",
    );
  }
  const backend = String(payload.backend ?? "").trim().toLowerCase();
  const report = (phase, percent, detail) =>
    setProgress(requestId, backend, phase, percent, detail);
  const workDirectory = join(tmpdir(), `meido-anime-sdk-${randomUUID()}`);
  const outputPath = join(workDirectory, "episode.mp4");
  mkdirSync(workDirectory, { recursive: true });
  report("starting", 0, "Starting downloader");
  try {
    await prepareDownload(payload, outputPath, report);
    const size = statSync(outputPath).size;
    report("streaming", 100, "Sending media to worker");
    response.writeHead(200, {
      "content-type": "video/mp4",
      "content-length": size,
      "x-meido-backend": String(payload.backend),
      "x-meido-contract-version": "1",
    });
    await pipeline(createReadStream(outputPath), response);
    report("complete", 100, "Media delivered to worker");
  } catch (error) {
    report("failed", 0, String(error?.message ?? error).slice(0, 300));
    throw error;
  } finally {
    rmSync(workDirectory, { recursive: true, force: true });
    scheduleProgressCleanup(requestId);
  }
}


const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host ?? "localhost"}`);
    if (request.method === "GET" && url.pathname === "/health/live") {
      sendJson(response, 200, { status: "ok" });
      return;
    }
    if (request.method === "GET" && url.pathname === "/health/ready") {
      sendJson(response, 200, {
        status: "ready",
        runtime: `anime-sdk ${SDK_VERSION}`,
        providers: [...providers.keys()],
        segment_concurrency: SEGMENT_CONCURRENCY,
      });
      return;
    }
    if (request.method === "GET" && url.pathname === "/v1/progress") {
      const requestId = url.searchParams.get("request_id") ?? "";
      const progress = progressStates.get(requestId);
      if (!progress) {
        sendProblem(
          response,
          new SidecarError(
            "not_found",
            404,
            "progress is not available for this request",
          ),
        );
        return;
      }
      sendJson(response, 200, progress);
      return;
    }
    if (request.method === "POST" && url.pathname === "/v1/download") {
      await handleDownload(request, response);
      return;
    }
    sendProblem(
      response,
      new SidecarError("not_found", 404, "route not found"),
    );
  } catch (error) {
    if (!response.headersSent) sendProblem(response, error);
    else response.destroy(error);
  }
});


server.listen(PORT, "0.0.0.0", () => {
  console.log(
    JSON.stringify({
      event: "ready",
      port: PORT,
      runtime: `anime-sdk ${SDK_VERSION}`,
      providers: [...providers.keys()],
      segment_concurrency: SEGMENT_CONCURRENCY,
    }),
  );
});
