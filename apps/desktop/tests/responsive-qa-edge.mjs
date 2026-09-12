import { spawn, spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const profile = await mkdtemp(path.join(tmpdir(), "geoplot-edge-qa-"));
const port = 9237;
const sizes = [
  [1180, 760],
  [900, 760],
  [760, 560],
];
const outputDirectory = path.join(tmpdir(), "geoplot-responsive-qa");
await mkdir(outputDirectory, { recursive: true });

const edgeProcess = spawn(edge, [
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  "about:blank",
], { stdio: "ignore", windowsHide: true });

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function findPage() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const pages = await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json());
      const page = pages.find((item) => item.type === "page");
      if (page) return page;
    } catch {
      // Edge may still be starting.
    }
    await delay(100);
  }
  throw new Error("Edge DevTools endpoint did not become available.");
}

const page = await findPage();
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextId = 1;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(String(event.data));
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});

function command(method, params = {}) {
  const id = nextId;
  nextId += 1;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text ?? "Browser evaluation failed.");
  }
  return result.result.value;
}

const interaction = String.raw`(async () => {
  const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  const waitFor = async (selector) => {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const element = document.querySelector(selector);
      if (element) return element;
      await delay(25);
    }
    throw new Error('Timed out waiting for ' + selector);
  };
  const findButton = (text) => [...document.querySelectorAll('button')]
    .find((button) => button.textContent.trim() === text);

  (await waitFor('input[aria-label="Select REE pattern"]')).click();
  await delay(50);
  const reference = await waitFor('select[aria-label="ree normalization reference"]');
  reference.value = 'chondrite-sm89';
  reference.dispatchEvent(new Event('change', { bubbles: true }));
  document.querySelectorAll('[aria-labelledby="confirmation-title"] .confirmation input')
    .forEach((input) => input.click());
  await delay(75);
  const createButton = findButton('Save reviewed recipe and create plan');
  if (!createButton || createButton.disabled) throw new Error('Plan creation gate did not unlock.');
  createButton.click();
  const planPanel = await waitFor('.plan-panel');
  planPanel.querySelector('.confirmation input').click();
  await delay(50);
  const runButton = findButton('Run reviewed plan locally');
  if (!runButton || runButton.disabled) throw new Error('Run gate did not unlock.');
  runButton.click();
  await waitFor('.artifact-view');
  await delay(75);
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' });
  await delay(50);

  const root = document.documentElement;
  const visibleControls = [...document.querySelectorAll('button,input,select')].filter((element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  });
  const clippedControls = visibleControls.filter((element) => {
    const rect = element.getBoundingClientRect();
    return rect.left < -0.5 || rect.right > window.innerWidth + 0.5;
  }).map((element) => element.getAttribute('aria-label') || element.textContent.trim().slice(0, 40));
  const artifact = document.querySelector('.artifact-view');
  const image = artifact.querySelector('img');
  const qa = artifact.querySelector('pre');
  const artifactColumns = getComputedStyle(artifact).gridTemplateColumns.split(' ').filter(Boolean).length;
  return {
    viewport: [window.innerWidth, window.innerHeight],
    scrollWidth: root.scrollWidth,
    clientWidth: root.clientWidth,
    globalHorizontalOverflow: root.scrollWidth > root.clientWidth,
    clippedControls,
    mappingRows: document.querySelectorAll('.mapping-row').length,
    unitControls: document.querySelectorAll('[aria-label$=" unit"]').length,
    planVisible: Boolean(planPanel),
    runVisible: Boolean(document.querySelector('.artifact-view')),
    artifactColumns,
    imageWidth: Math.round(image.getBoundingClientRect().width),
    artifactWidth: Math.round(artifact.getBoundingClientRect().width),
    qaHasLocalOverflow: qa.scrollWidth > qa.clientWidth,
  };
})()`;

const results = [];
try {
  await command("Page.enable");
  await command("Runtime.enable");
  for (const [width, height] of sizes) {
    await command("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await command("Page.navigate", { url: "http://127.0.0.1:5173/tests/responsive-app.html" });
    await delay(500);
    const metrics = await evaluate(interaction);
    const screenshot = await command("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    const screenshotPath = path.join(outputDirectory, `post-run-${width}x${height}.png`);
    await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
    results.push({ ...metrics, screenshotPath });
  }
  process.stdout.write(`${JSON.stringify(results, null, 2)}\n`);
  if (results.some((result) => result.globalHorizontalOverflow || result.clippedControls.length > 0)) {
    process.exitCode = 1;
  }
} finally {
  socket.close();
  edgeProcess.kill();
  spawnSync("taskkill", ["/PID", String(edgeProcess.pid), "/T", "/F"], {
    stdio: "ignore",
    windowsHide: true,
  });
  const normalizedProfile = path.resolve(profile);
  if (path.dirname(normalizedProfile) !== path.resolve(tmpdir()) || !path.basename(normalizedProfile).startsWith("geoplot-edge-qa-")) {
    throw new Error(`Refusing to clean unexpected browser profile: ${normalizedProfile}`);
  }
  const stopProfileProcesses = String.raw`
    $target = $args[0]
    Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'" |
      Where-Object { $_.CommandLine -and $_.CommandLine.Contains($target) } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  `;
  spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", stopProfileProcesses, normalizedProfile], {
    stdio: "ignore",
    windowsHide: true,
  });
  await delay(750);
  let cleanupError;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    try {
      await rm(normalizedProfile, { recursive: true, force: true });
      cleanupError = undefined;
      break;
    } catch (caught) {
      cleanupError = caught;
      await delay(250);
    }
  }
  if (cleanupError) throw cleanupError;
}
