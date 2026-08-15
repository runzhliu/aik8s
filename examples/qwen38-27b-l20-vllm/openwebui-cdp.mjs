import { writeFile } from "node:fs/promises";

const action = process.argv[2] ?? "inspect";
const screenshotPath = process.argv[3];
const pages = await (await fetch("http://127.0.0.1:9222/json")).json();
const page = pages.find((item) => item.type === "page");

if (!page) {
  throw new Error("No Chrome page target found on port 9222");
}

const socket = new WebSocket(page.webSocketDebuggerUrl);
const pending = new Map();
let nextId = 1;

await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(JSON.stringify(message.error)));
  else resolve(message.result);
});

function send(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text);
  }
  return result.result.value;
}

await send("Page.enable");
await send("Runtime.enable");

if (action === "inspect") {
  const state = await evaluate(`({
    title: document.title,
    readyState: document.readyState,
    bodyText: document.body.innerText.slice(0, 5000),
    fields: [...document.querySelectorAll('textarea, input, [contenteditable="true"]')].map((node) => ({
      tag: node.tagName,
      id: node.id,
      type: node.type,
      placeholder: node.getAttribute('placeholder'),
      ariaLabel: node.getAttribute('aria-label')
    })),
    buttons: [...document.querySelectorAll('button')].map((node) => ({
      text: node.innerText,
      title: node.getAttribute('title'),
      ariaLabel: node.getAttribute('aria-label')
    })).filter((item) => item.text || item.title || item.ariaLabel).slice(0, 100)
  })`);
  process.stdout.write(`${JSON.stringify(state, null, 2)}\n`);
} else if (action === "models") {
  if (!screenshotPath) throw new Error("models action requires a screenshot path");
  const opened = await evaluate(`(() => {
    const button = document.querySelector('button[aria-label^="Selected model:"]');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!opened) throw new Error("Selected model button not found");
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const screenshot = await send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
    fromSurface: true,
  });
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  process.stdout.write(`${JSON.stringify({ screenshotPath }, null, 2)}\n`);
} else if (action === "chat") {
  if (!screenshotPath) throw new Error("chat action requires a screenshot path");
  const prompt = "只回复：Qwen3.8-27B FP8 已在 L20 上通过 OpenWebUI 调用。";
  const focused = await evaluate(`(() => {
    const field = document.querySelector('#chat-input')
      || document.querySelector('textarea')
      || document.querySelector('[contenteditable="true"]');
    if (!field) return { ok: false, reason: 'chat input not found' };
    field.focus();
    return { ok: true, tag: field.tagName };
  })()`);
  if (!focused.ok) throw new Error(focused.reason);
  await send("Input.insertText", { text: prompt });
  await new Promise((resolve) => setTimeout(resolve, 500));

  const submitted = await evaluate(`(() => {
    const sendButton = document.querySelector('#send-message-button')
      || [...document.querySelectorAll('button')].find((button) => /send|发送/i.test(
        [button.innerText, button.getAttribute('aria-label'), button.getAttribute('title')].filter(Boolean).join(' ')
      ));
    if (sendButton) {
      sendButton.click();
      return { ok: true, method: 'button' };
    }
    field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    field.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
    return { ok: true, method: 'keyboard' };
  })()`);

  const deadline = Date.now() + 120_000;
  let bodyText = "";
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    bodyText = await evaluate("document.body.innerText");
    const occurrences = bodyText.split("Qwen3.8-27B FP8 已在 L20 上通过 OpenWebUI 调用。").length - 1;
    if (occurrences >= 2) break;
  }
  const occurrences = bodyText.split("Qwen3.8-27B FP8 已在 L20 上通过 OpenWebUI 调用。").length - 1;
  if (occurrences < 2) {
    throw new Error("Timed out waiting for the expected OpenWebUI response");
  }
  await new Promise((resolve) => setTimeout(resolve, 1500));
  const screenshot = await send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
    fromSurface: true,
  });
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  process.stdout.write(`${JSON.stringify({ submitted, screenshotPath }, null, 2)}\n`);
} else {
  throw new Error(`Unknown action: ${action}`);
}

socket.close();
