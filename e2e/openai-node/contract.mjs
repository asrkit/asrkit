import fs from "node:fs";
import OpenAI from "openai";

const MODEL = "sdk/echo";
const TRANSCRIPT = "hello from the ASRKit SDK contract";

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const fixture = required("ASRKIT_AUDIO_FIXTURE");
if (!fs.statSync(fixture).isFile()) throw new Error(`audio fixture does not exist: ${fixture}`);

const client = new OpenAI({
  apiKey: required("ASRKIT_SDK_TOKEN"),
  baseURL: `${required("ASRKIT_BASE_URL").replace(/\/$/, "")}/v1`,
});

const models = await client.models.list();
if (!models.data.some((model) => model.id === MODEL)) throw new Error(`missing model ${MODEL}`);

const result = await client.audio.transcriptions.create({
  file: fs.createReadStream(fixture),
  model: MODEL,
});
if (result.text !== TRANSCRIPT) throw new Error(`unexpected JSON transcript: ${result.text}`);

const text = await client.audio.transcriptions.create({
  file: fs.createReadStream(fixture),
  model: MODEL,
  response_format: "text",
});
if (text !== TRANSCRIPT) throw new Error(`unexpected text transcript: ${text}`);

const verbose = await client.audio.transcriptions.create({
  file: fs.createReadStream(fixture),
  model: MODEL,
  language: "en",
  response_format: "verbose_json",
});
if (verbose.text !== TRANSCRIPT) throw new Error(`unexpected verbose transcript: ${verbose.text}`);
if (verbose.language !== "en") throw new Error(`unexpected language: ${verbose.language}`);
if (verbose.segments?.[0]?.text !== TRANSCRIPT) throw new Error("missing verbose segment");
